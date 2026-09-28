"""Renders the Seestar model pictures for the dashboard with Blender.

Original 3D models built from primitives (not product photos or CAD),
lit like a product shot and composited onto the same light rounded tile
as upstream's Dwarf pictures.

    blender -b -P tools/render_seestars.py -- [out_dir] [model ...]

Models: s50 s50pro s30 s30pro (default: all). Output: seestar-<model>.png.
"""
from __future__ import annotations

import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector

W, H = 540, 560                  # 2x upstream's 270x280 tiles
TILE_RADIUS = 92
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT_DIR = argv[0] if argv else os.path.join(REPO, "smartscopes", "ui", "images")
MODELS = argv[1:] or ["s50", "s50pro", "s30", "s30pro"]


# --- scene -----------------------------------------------------------------------

def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 256
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = W, H
    scene.render.film_transparent = True
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = 0.55
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("OPTIX", "CUDA", "HIP"):
            try:
                prefs.compute_device_type = backend
                prefs.get_devices()
                if any(d.type == backend for d in prefs.devices):
                    for d in prefs.devices:
                        d.use = d.type == backend
                    scene.cycles.device = "GPU"
                    break
            except TypeError:
                continue
    except KeyError:
        pass

    world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.9, 0.91, 0.93, 1)
    bg.inputs["Strength"].default_value = 0.75
    return scene


def material(name, color, rough, metal=0.0, coat=0.0, emission=None, strength=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["Coat Weight"].default_value = coat
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1)
        bsdf.inputs["Emission Strength"].default_value = strength
    return mat


def ribbed(mat, scale=1.15, depth=0.3):
    """Fine parallel ribs (bump only), like the S50's textured side."""
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    coord = nt.nodes.new("ShaderNodeTexCoord")
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.wave_type = "BANDS"
    wave.bands_direction = "DIAGONAL"
    wave.inputs["Scale"].default_value = scale
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = depth
    nt.links.new(coord.outputs["Object"], wave.inputs["Vector"])
    nt.links.new(wave.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.012, 0.012, 0.014, 1)
    ramp.color_ramp.elements[1].color = (0.065, 0.065, 0.07, 1)
    nt.links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def finish(obj, mat, bevel=0.0, segments=6):
    obj.data.materials.append(mat)
    for poly in obj.data.polygons:
        poly.use_smooth = True
    if bevel:
        mod = obj.modifiers.new("Bevel", "BEVEL")
        mod.width = bevel
        mod.segments = segments
        mod.limit_method = "ANGLE"
    obj.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL").keep_sharp = True
    return obj


def box(name, size, loc, mat, bevel=0.3, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    obj = bpy.context.object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(scale=True)
    return finish(obj, mat, bevel)


def cylinder(name, radius, depth, loc, mat, axis=(0, 0, 1), bevel=0.0, verts=64):
    rot = Vector((0, 0, 1)).rotation_difference(Vector(axis).normalized()).to_euler()
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=radius, depth=depth, location=loc, rotation=rot)
    obj = bpy.context.object
    obj.name = name
    return finish(obj, mat, bevel, segments=4)


def hull_prism(name, circles, x0, x1, mat, bevel=0.6):
    """Extrudes the convex hull of circles (y, z, r) in the Y-Z plane from x0 to x1."""
    bm = bmesh.new()
    for x in (x0, x1):
        for (y, z, r) in circles:
            for i in range(48):
                a = 2 * math.pi * i / 48
                bm.verts.new((x, y + r * math.cos(a), z + r * math.sin(a)))
    bmesh.ops.convex_hull(bm, input=list(bm.verts))
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return finish(obj, mat, bevel, segments=5)


def lens(center, direction, radius, mats, ring=0.35):
    d = Vector(direction).normalized()
    c = Vector(center)
    cylinder("lens_bezel", radius + ring, 0.8, c, mats["gloss_black"], axis=d, bevel=0.12)
    cylinder("lens_coating", radius * 0.92, 0.2, c + d * 0.36, mats["coating"], axis=d)
    cylinder("lens_glass", radius * 0.78, 0.2, c + d * 0.44, mats["glass"], axis=d)


def tripod(top_z, foot_z, spread, mats, leg_r=0.75, hub_r=1.8):
    cylinder("tripod_hub", hub_r, 2.2, (0, 0.6, top_z - 1.1), mats["metal"], bevel=0.2)
    for k in range(3):
        a = math.radians(90 + 120 * k)
        foot = Vector((spread * math.cos(a), spread * math.sin(a) + 0.6, foot_z))
        top = Vector((0.9 * math.cos(a), 0.9 * math.sin(a) + 0.6, top_z - 2.0))
        mid = (foot + top) / 2
        cylinder("tripod_leg", leg_r * 0.7, (foot - top).length, mid, mats["metal"], axis=foot - top, bevel=0.1)
        grip = top + (foot - top) * 0.42
        cylinder("tripod_grip", leg_r, (foot - top).length * 0.62, grip, mats["rubber"], axis=foot - top, bevel=0.25)
        cylinder("tripod_foot", leg_r * 1.35, 1.2, foot + (top - foot).normalized() * 0.6,
                 mats["metal"], axis=foot - top, bevel=0.15)


# --- models (cm, Z up, front faces -Y) --------------------------------------------------

def s50_head_outline(center, d, length, width, inset=0.0):
    """Side profile of the S50 head as hull circles (y, z, r): a flat,
    full-width lens end with rounded corners, rounding off towards a
    slightly pointed far end (like a guitar pick). `inset` shrinks it."""
    n = Vector((d.y, -d.x))                        # perpendicular to the tube axis
    c = Vector(center)
    front = c + d * (length / 2)
    rc, r_back, r_tip = 1.6, width / 2, 2.6
    pts = [
        (front + n * (width / 2 - rc) - d * rc, rc),                     # lens-end corners
        (front - n * (width / 2 - rc) - d * rc, rc),
        (c - d * (length / 2 - r_back) + n * 0.4, r_back),               # rounded body
        (c - d * (length / 2 - r_tip) - n * 1.3, r_tip),                 # slight point, lower back
    ]
    return [(p.x, p.y, max(r - inset, 0.3)) for p, r in pts]


def build_s50(m):
    # Base block running front-to-back, fork arm rising at the front on -X,
    # optical head on +X with a flat full-width lens end (top front) and a
    # rounded far end; ribbed raised panel on its outer side; long tripod.
    box("base", (13.5, 12.5, 5), (0, 1.5, 2.5), m["black"], bevel=0.8)
    box("arm", (3.6, 7.5, 14), (-5.2, -1.2, 12.0), m["black"], bevel=0.8)
    cylinder("arm_top", 3.75, 3.6, (-5.2, -1.2, 19.0), m["black"], axis=(1, 0, 0), bevel=0.7)

    d2 = Vector((-math.cos(math.radians(42)), math.sin(math.radians(42))))  # (y, z), towards the lens
    center, length, width = (1.2, 14.2), 13.5, 10.5
    x0, x1 = -3.3, 5.6
    hull_prism("head", s50_head_outline(center, d2, length, width), x0, x1, m["black"], bevel=0.7)
    hull_prism("head_panel", s50_head_outline(center, d2, length, width, inset=1.1),
               x1 - 0.3, x1 + 0.18, ribbed(m["black_ribbed"]), bevel=0.12)

    d = Vector((0, d2.x, d2.y))
    front = Vector((0, center[0], center[1])) + d * (length / 2)
    lens(Vector(((x0 + x1) / 2, front.y, front.z)), d, 3.3, m, ring=0.45)
    tripod(0, -14, 8.0, m)


def build_s50pro(m):
    # White rounded body with a black front pill, white head with lens at top right.
    box("body", (8.4, 8, 20.5), (0, 0, 10.25), m["white"], bevel=2.6)
    box("panel", (3.2, 0.5, 15.5), (-1.9, -3.95, 10.5), m["gloss_black"], bevel=1.5)
    cylinder("light", 0.55, 0.3, (-1.9, -4.25, 4.2), m["amber"], axis=(0, -1, 0))
    # Head sticks out to the upper right, lens on its front face.
    box("head", (8.8, 8.2, 9.8), (7.0, 0.2, 16.0), m["white"], bevel=3.6)
    lens(Vector((7.6, -3.95, 16.9)), (0, -1, 0), 2.7, m)
    cylinder("sensor", 0.38, 0.3, (9.7, -3.95, 13.3), m["gloss_black"], axis=(0, -1, 0))
    tripod(0, -16, 10.5, m)


def build_s30(m):
    # White box, head folded into its right side (groove + lens slit), short tripod.
    box("body", (5.4, 6.4, 14.5), (-1.6, 0, 7.25), m["white"], bevel=0.9)
    box("head", (3.3, 6.4, 11.2), (2.85, 0, 8.9), m["white"], bevel=0.9)
    box("foot", (3.3, 5.4, 3.0), (2.85, 0.4, 1.5), m["white_shadow"], bevel=0.5)
    box("slit", (2.7, 0.3, 0.7), (2.85, -3.2, 4.0), m["gloss_black"], bevel=0.25)
    cylinder("slit_glass", 0.28, 1.6, (2.85, -3.35, 4.0), m["glass"], axis=(1, 0, 0))
    tripod(0, -6.5, 8.5, m, leg_r=0.5, hub_r=1.3)


def build_s30pro(m):
    # White body with black LED pill; black square tube angled up at the top right.
    box("body", (8, 7, 16.5), (0, 0, 8.25), m["white"], bevel=2.2)
    box("panel", (3.4, 0.5, 12.5), (-1.9, -3.45, 8.2), m["gloss_black"], bevel=1.6)
    for i in range(4):
        cylinder("led", 0.2, 0.25, (-1.2, -3.75, 12.0 - i * 0.9), m["red_led"], axis=(0, -1, 0), verts=16)
    cylinder("button", 0.6, 0.3, (-1.9, -3.75, 3.6), m["amber"], axis=(0, -1, 0))
    tube_dir = Vector((math.cos(math.radians(36)), 0, math.sin(math.radians(36))))
    tube_center = Vector((6.2, 0.2, 15.0))
    box("tube", (10.5, 4.8, 4.8), tube_center, m["black"], bevel=0.6, rot=(0, -math.radians(36), 0))
    lens(tube_center + tube_dir * 5.35, tube_dir, 1.75, m, ring=0.45)
    tripod(0, -6.5, 9.5, m, leg_r=0.5, hub_r=1.3)


BUILDERS = {"s50": build_s50, "s50pro": build_s50pro, "s30": build_s30, "s30pro": build_s30pro}


def materials():
    return {
        "black": material("black", (0.022, 0.022, 0.025), 0.55),
        "black_ribbed": material("black_ribbed", (0.022, 0.022, 0.025), 0.5),
        "gloss_black": material("gloss_black", (0.012, 0.012, 0.014), 0.12, coat=0.6),
        "white": material("white", (0.93, 0.93, 0.94), 0.3, coat=0.3),
        "white_shadow": material("white_shadow", (0.74, 0.74, 0.76), 0.4),
        "glass": material("glass", (0.01, 0.02, 0.02), 0.02, coat=1.0),
        "coating": material("coating", (0.04, 0.22, 0.14), 0.08, metal=0.6),
        "metal": material("metal", (0.08, 0.08, 0.09), 0.35, metal=1.0),
        "rubber": material("rubber", (0.02, 0.02, 0.022), 0.75),
        "amber": material("amber", (1.0, 0.55, 0.15), 0.3, emission=(1.0, 0.55, 0.15), strength=4),
        "red_led": material("red_led", (1.0, 0.05, 0.05), 0.3, emission=(1.0, 0.05, 0.05), strength=6),
    }


# --- lights, camera, framing ------------------------------------------------------------------

def add_light(name, loc, energy, size, color=(1, 1, 1)):
    data = bpy.data.lights.new(name, "AREA")
    data.energy, data.size, data.color = energy, size, color
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = loc
    obj.rotation_euler = (Vector((0, 0, 8)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()


VIEWS = {  # camera direction (from the model towards the camera)
    "s50": (1.0, -0.42, 0.26),      # side-on: shows the teardrop head's ribbed face
    "s50pro": (-0.42, -1.0, 0.22),
    "s30": (-0.5, -1.0, 0.22),
    "s30pro": (-0.42, -1.0, 0.22),
}


def frame(scene, model):
    objs = [o for o in scene.objects if o.type == "MESH" and not o.is_shadow_catcher]
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    center = (lo + hi) / 2

    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    view = Vector(VIEWS[model]).normalized()
    cam.location = center + view * 80
    cam.rotation_euler = (-view).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    bpy.context.view_layer.update()

    # Frame on the telescope body (not the tripod), like upstream's Dwarf
    # tiles: body large and near the top, tripod running off the bottom.
    # Ortho scale spans the image height (H > W, sensor fit AUTO).
    inv = cam.matrix_world.inverted()
    body = [inv @ (o.matrix_world @ Vector(c)) for o in objs if not o.name.startswith("tripod")
            for c in o.bound_box]
    xs, ys = [p.x for p in body], [p.y for p in body]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    scale = max(width / (0.74 * W / H), height / 0.64)
    cam_data.ortho_scale = scale
    cam_data.shift_x = (max(xs) + min(xs)) / 2 / scale
    cam_data.shift_y = (max(ys) - 0.38 * scale) / scale
    return lo.z


def shadow_floor(z):
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, z - 0.3))
    bpy.context.object.is_shadow_catcher = True


# --- tile compositing ---------------------------------------------------------------------------

def rounded_tile():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    inset = 12
    x0, y0, x1, y1, r = inset, inset, W - 1 - inset, H - 1 - inset, TILE_RADIUS
    cx = np.clip(xx, x0 + r, x1 - r)
    cy = np.clip(yy, y0 + r, y1 - r)
    dist = np.hypot(xx - cx, yy - cy) - r              # <0 inside the rounded rect
    alpha = np.clip(0.5 - dist, 0, 1)
    t = (yy - y0) / (y1 - y0)                          # 0 bottom .. 1 top (Blender rows are bottom-up)
    top, bottom = np.array([1.0, 1.0, 1.0]), np.array([0.885, 0.895, 0.915])
    rgb = bottom + (top - bottom) * t[..., None]
    border = np.clip(1.5 - np.abs(dist + 1.2), 0, 1)[..., None]
    rgb = rgb * (1 - border * 0.35) + np.array([0.80, 0.81, 0.83]) * border * 0.35
    return np.dstack([rgb, alpha])


def composite(render_path, out_path):
    img = bpy.data.images.load(render_path)
    fg = np.array(img.pixels[:], dtype=np.float32).reshape(H, W, 4)
    tile = rounded_tile()
    a = fg[..., 3:4]
    rgb = fg[..., :3] + tile[..., :3] * (1 - a)       # render is premultiplied
    alpha = np.maximum(tile[..., 3:4], a) * tile[..., 3:4]
    out = bpy.data.images.new("tile", W, H, alpha=True)
    out.pixels = np.dstack([rgb, alpha]).ravel()
    out.filepath_raw = out_path
    out.file_format = "PNG"
    out.save()


def render(model):
    scene = reset_scene()
    mats = materials()
    BUILDERS[model](mats)
    floor_z = frame(scene, model)
    shadow_floor(floor_z)
    # Key light on the camera's side, so it mirrors with the view.
    sx = 1 if VIEWS[model][0] > 0 else -1
    add_light("key", (30 * sx, -34, 42), 5200, 26)
    add_light("fill", (-34 * sx, -26, 18), 1600, 30, (0.95, 0.97, 1.0))
    add_light("rim", (-10 * sx, 40, 38), 2600, 18)
    tmp = os.path.join(bpy.app.tempdir or "/tmp", f"seestar-{model}-raw.png")
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = tmp
    bpy.ops.render.render(write_still=True)
    out = os.path.join(OUT_DIR, f"seestar-{model}.png")
    composite(tmp, out)
    print(f"rendered {out}")


os.makedirs(OUT_DIR, exist_ok=True)
for name in MODELS:
    render(name)
