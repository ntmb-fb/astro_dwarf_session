"""Generates the pencil-sketch SVGs of the Seestar models in smartscopes/ui/images/.

Original drawings (not product photos). Run: python tools/make_seestar_sketches.py
"""
import sys
from pathlib import Path

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "smartscopes" / "ui" / "images"

DEFS = """
  <defs>
    <filter id="pencil" x="-5%" y="-5%" width="110%" height="110%">
      <feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="2" seed="{seed}" result="n"/>
      <feDisplacementMap in="SourceGraphic" in2="n" scale="2.4" xChannelSelector="R" yChannelSelector="G"/>
    </filter>
    <filter id="grain">
      <feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves="1" seed="3" result="g"/>
      <feColorMatrix in="g" type="matrix" values="0 0 0 0 0.35  0 0 0 0 0.33  0 0 0 0 0.3  0 0 0 0.10 0"/>
      <feComposite in2="SourceGraphic" operator="in"/>
    </filter>
    <pattern id="hatchL" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(38)">
      <line x1="0" y1="0" x2="0" y2="7" stroke="#6f6f6f" stroke-width="0.8" opacity="0.55"/>
    </pattern>
    <pattern id="hatchM" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(38)">
      <line x1="0" y1="0" x2="0" y2="4" stroke="#555" stroke-width="0.8" opacity="0.7"/>
    </pattern>
    <pattern id="hatchD" width="3.2" height="3.2" patternUnits="userSpaceOnUse" patternTransform="rotate(38)">
      <line x1="0" y1="0" x2="0" y2="3.2" stroke="#3a3a3a" stroke-width="0.9"/>
    </pattern>
    <pattern id="hatchX" width="3.6" height="3.6" patternUnits="userSpaceOnUse" patternTransform="rotate(-42)">
      <line x1="0" y1="0" x2="0" y2="3.6" stroke="#444" stroke-width="0.8" opacity="0.85"/>
    </pattern>
    <radialGradient id="glass" cx="0.38" cy="0.35" r="0.75">
      <stop offset="0" stop-color="#d9d9d9"/>
      <stop offset="0.45" stop-color="#7a7a7a"/>
      <stop offset="1" stop-color="#2e2e2e"/>
    </radialGradient>
  </defs>"""

TILE = """
  <rect x="6" y="6" width="258" height="268" rx="46" fill="#fbfaf6" stroke="#d8d5cc"/>
  <rect x="6" y="6" width="258" height="268" rx="46" fill="#fbfaf6" filter="url(#grain)"/>"""


def dark(shape: str) -> str:
    """A black part: graphite wash + dense cross-hatching + outline."""
    return f"""
    {shape.replace('/>', ' fill="#fbfaf6"/>')}
    {shape.replace('/>', ' fill="#8d8d8d" opacity="0.45"/>')}
    {shape.replace('/>', ' fill="url(#hatchD)"/>')}
    {shape.replace('/>', ' fill="url(#hatchX)"/>')}
    {shape.replace('/>', ' fill="none" stroke="#2b2b2b" stroke-width="1.7"/>')}"""


def white(shape: str, shade: str | None = None) -> str:
    """A white part: paper fill, light hatching in `shade` region, outline twice."""
    out = shape.replace('/>', ' fill="#fdfdfb"/>')
    if shade:
        out += "\n    " + shade.replace('/>', ' fill="url(#hatchL)"/>')
    out += "\n    " + shape.replace('/>', ' fill="none" stroke="#3b3b3b" stroke-width="1.5"/>')
    out += "\n    " + shape.replace('/>', ' fill="none" stroke="#6a6a6a" stroke-width="0.7" transform="translate(0.8 -0.6)"/>')
    return out


def tripod(top_y: float, foot_y: float, spread: float, cx: float = 135) -> str:
    legs = []
    for dx in (-spread, 0, spread):
        x2 = cx + dx
        y2 = foot_y if dx else foot_y + 4
        legs.append(f'<line x1="{cx}" y1="{top_y}" x2="{x2}" y2="{y2}" stroke="#2f2f2f" stroke-width="7.5" stroke-linecap="round"/>')
        legs.append(f'<line x1="{cx}" y1="{top_y}" x2="{x2}" y2="{y2}" stroke="url(#hatchD)" stroke-width="6" stroke-linecap="round"/>')
        legs.append(f'<line x1="{cx - 1.5}" y1="{top_y}" x2="{x2 - 1.5}" y2="{y2}" stroke="#bbb" stroke-width="0.8"/>')
    hub = f'<rect x="{cx - 15}" y="{top_y - 8}" width="30" height="12" rx="4" fill="#3a3a3a"/>'
    return "\n    ".join(legs + [hub])


def svg(name: str, seed: int, body: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 270 280" width="270" height="280">
  <!-- Original pencil sketch of a {name}-style smart telescope (not a product photo). -->{DEFS.format(seed=seed)}{TILE}
  <g filter="url(#pencil)">{body}
  </g>
</svg>
"""


# --- Seestar S50: black fork arm, teardrop head, long tripod -------------------------------
s50 = f"""
    {tripod(196, 262, 42)}
    {dark('<rect x="74" y="152" width="126" height="40" rx="7"/>')}
    {dark('<path d="M150 190 V72 a29 29 0 0 1 58 0 V190 Z"/>')}
    <circle cx="179" cy="88" r="15" fill="none" stroke="#2b2b2b" stroke-width="1.4"/>
    <g transform="rotate(-24 128 104)">
      {dark('<path d="M62 104 C62 80 82 71 104 71 H150 C177 71 194 88 194 113 C194 138 176 153 150 153 H104 C82 153 62 128 62 104 Z"/>')}
      <ellipse cx="63" cy="104" rx="11" ry="30" fill="#2b2b2b"/>
      <ellipse cx="64" cy="104" rx="7" ry="22" fill="url(#glass)"/>
      <ellipse cx="61" cy="95" rx="1.8" ry="6" fill="#fff" opacity="0.8"/>
    </g>"""

# --- Seestar S50 Pro: white rounded body, black front panel, white head with lens top-right
s50pro = f"""
    {tripod(214, 262, 46)}
    {white('<path d="M76 92 a30 30 0 0 1 30 -30 H138 a22 22 0 0 1 22 22 V192 a26 26 0 0 1 -26 26 H100 a24 24 0 0 1 -24 -24 Z"/>', '<rect x="140" y="150" width="20" height="64" rx="8"/>')}
    {white('<path d="M128 84 a38 36 0 0 1 76 0 V120 a34 34 0 0 1 -34 34 H150 a22 22 0 0 1 -22 -22 Z"/>', '<path d="M190 58 a24 30 0 0 1 14 26 V120 a34 34 0 0 1 -14 27 Z"/>')}
    <path d="M160 154 V192" stroke="#3b3b3b" stroke-width="1.2"/>
    {dark('<rect x="86" y="80" width="30" height="124" rx="15"/>')}
    <circle cx="101" cy="188" r="4.2" fill="#e9e9e9" stroke="#2b2b2b" stroke-width="1"/>
    <circle cx="172" cy="94" r="20" fill="#2b2b2b"/>
    <circle cx="172" cy="94" r="14" fill="url(#glass)"/>
    <circle cx="167" cy="89" r="3.2" fill="#fff" opacity="0.85"/>
    <circle cx="183" cy="116" r="3" fill="none" stroke="#3b3b3b" stroke-width="1"/>"""

# --- Seestar S30 Pro: white body, black panel with LEDs, black tube angled up to the right, short tripod
s30pro = f"""
    {tripod(232, 258, 58)}
    <g transform="rotate(-34 170 112)">
      {dark('<rect x="140" y="92" width="92" height="44" rx="6"/>')}
      <rect x="222" y="95" width="12" height="38" rx="3" fill="#2b2b2b"/>
      <ellipse cx="236" cy="114" rx="6" ry="15" fill="url(#glass)"/>
    </g>
    {white('<path d="M84 110 a24 24 0 0 1 24 -24 H158 a18 18 0 0 1 18 18 V226 a10 10 0 0 1 -10 10 H94 a10 10 0 0 1 -10 -10 Z"/>', '<rect x="156" y="100" width="20" height="134" rx="8"/>')}
    {dark('<rect x="92" y="100" width="32" height="124" rx="16"/>')}
    <circle cx="112" cy="130" r="1.7" fill="#fff"/><circle cx="112" cy="140" r="1.7" fill="#fff"/>
    <circle cx="112" cy="150" r="1.7" fill="#fff"/><circle cx="112" cy="160" r="1.7" fill="#fff"/>
    <circle cx="108" cy="208" r="4.5" fill="#e9e9e9" stroke="#2b2b2b" stroke-width="1"/>"""

# --- Seestar S30: white box, head folded into its side, short tripod
s30 = f"""
    {tripod(226, 258, 54)}
    {white('<rect x="80" y="70" width="110" height="160" rx="12"/>', '<rect x="176" y="74" width="14" height="152" rx="6"/>')}
    {white('<path d="M136 70 H176 a14 14 0 0 1 14 14 V196 H136 Z"/>', '<rect x="166" y="72" width="22" height="122"/>')}
    {dark('<rect x="138" y="186" width="50" height="10" rx="3"/>')}
    <ellipse cx="163" cy="191" rx="9" ry="2.6" fill="url(#glass)"/>
    <line x1="136" y1="196" x2="136" y2="230" stroke="#3b3b3b" stroke-width="1.3"/>
    <line x1="136" y1="210" x2="190" y2="210" stroke="#3b3b3b" stroke-width="1.3"/>
    <rect x="137" y="211" width="52" height="18" fill="url(#hatchM)"/>"""

OUT.mkdir(parents=True, exist_ok=True)
for fname, name, seed, body in (("seestar-s50.svg", "Seestar S50", 7, s50),
                                ("seestar-s50pro.svg", "Seestar S50 Pro", 11, s50pro),
                                ("seestar-s30pro.svg", "Seestar S30 Pro", 5, s30pro),
                                ("seestar-s30.svg", "Seestar S30", 9, s30)):
    (OUT / fname).write_text(svg(name, seed, body))
print("written")
