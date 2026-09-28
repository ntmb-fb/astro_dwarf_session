"""RA/Dec parsing for program files.

Program files store coordinates either as decimal numbers (RA in hours,
Dec in degrees - what the program editor writes) or as sexagesimal
strings ("05:35:17.3", "-05:23:28"). Also accepts "5h35m17s" /
"-5d23m28s" as pasted from planetarium software.
"""
from __future__ import annotations

import re

_SEPARATORS = re.compile(r"[hHdD°:'′\"″ms\s]+")


def _sexagesimal(value: str) -> float:
    text = value.strip()
    negative = text.startswith("-")
    text = text.lstrip("+-").strip()
    parts = [p for p in _SEPARATORS.split(text) if p]
    if not parts or len(parts) > 3:
        raise ValueError(f"Unparseable coordinate: {value!r}")
    numbers = [float(p) for p in parts] + [0.0] * (3 - len(parts))
    magnitude = numbers[0] + numbers[1] / 60 + numbers[2] / 3600
    return -magnitude if negative else magnitude


def parse_ra_hours(value) -> float:
    if isinstance(value, (int, float)):
        ra = float(value)
    else:
        text = str(value).strip()
        try:
            ra = float(text)
        except ValueError:
            ra = _sexagesimal(text)
    if not 0 <= ra < 24:
        raise ValueError(f"RA out of range (0-24h): {value!r}")
    return ra


def parse_dec_deg(value) -> float:
    if isinstance(value, (int, float)):
        dec = float(value)
    else:
        text = str(value).strip()
        try:
            dec = float(text)
        except ValueError:
            dec = _sexagesimal(text)
    if not -90 <= dec <= 90:
        raise ValueError(f"Dec out of range (-90..90): {value!r}")
    return dec
