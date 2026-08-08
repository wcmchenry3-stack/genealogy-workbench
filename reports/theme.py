#!/usr/bin/env python3
"""
reports/theme.py
----------------
One visual language for every HTML report.

Reports import `page()` and the colour roles from here rather than styling
themselves. That is what makes eight reports from two different origins read as
one product. The categorical palette is validated for colour-vision deficiency
and for contrast in both light and dark mode -- do not substitute ad-hoc hexes.

Palette roles (validated adjacent-pair CVD separation, light and dark):
  s0 blue   s1 orange   s2 aqua   s3 yellow   s4 magenta   s5 green   s6 violet
Map/marker categories use only the first three slots, which additionally clear
the all-pairs gate needed when marks sit next to each other arbitrarily.
"""
from __future__ import annotations

import html
from pathlib import Path

EVENT_SLOT = {
    "Birth": 0, "Baptism": 0, "Christening": 0,
    "Residence": 2, "Census": 3, "Marriage": 5, "Probate": 6,
    "Immigration": 6, "Naturalization": 6, "Emigration": 6, "Military": 6,
    "Death": 4, "Burial": 1, "Event": 3,
}
EVENT_ORDER = ["Birth", "Baptism", "Residence", "Census", "Marriage", "Immigration",
               "Probate", "Military", "Death", "Burial"]
MAP_CATEGORY = {  # coarse grouping used for map pins
    "Birth": "vital", "Baptism": "vital", "Christening": "vital", "Death": "vital",
    "Marriage": "vital", "Burial": "cemetery",
    "Residence": "residence", "Census": "residence", "Probate": "residence",
    "Immigration": "residence", "Naturalization": "residence",
    "Emigration": "residence", "Military": "residence", "Event": "residence",
}

CSS = """
:root{color-scheme:light dark;
 --surface-1:#fcfcfb;--surface-2:#f4f4f1;--surface-3:#eceae5;--line:#e2e1dc;
 --text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#7a7975;
 --s0:#2a78d6;--s1:#eb6834;--s2:#1baf7a;--s3:#eda100;--s4:#e87ba4;--s5:#008300;--s6:#4a3aa7;
 --vital:#2a78d6;--cemetery:#eb6834;--residence:#1baf7a;}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])){
 --surface-1:#1a1a19;--surface-2:#232322;--surface-3:#2c2c2a;--line:#373735;
 --text-primary:#fff;--text-secondary:#c3c2b7;--text-muted:#95948c;
 --s0:#3987e5;--s1:#d95926;--s2:#199e70;--s3:#c98500;--s4:#d55181;--s5:#008300;--s6:#9085e9;
 --vital:#3987e5;--cemetery:#d95926;--residence:#199e70;}}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-1);color:var(--text-primary);
 font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:36px 24px 80px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:-.02em}
h2{font-size:19px;margin:36px 0 12px;letter-spacing:-.01em}
h3{font-size:16.5px;margin:0 0 2px}
.sub{color:var(--text-secondary);margin:0 0 22px;font-size:14px;max-width:76ch}
.meta{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 24px}
.chip{background:var(--surface-2);border:1px solid var(--line);border-radius:999px;
 padding:4px 11px;font-size:12.5px;color:var(--text-secondary)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th{text-align:left;font-weight:600;font-size:11.5px;text-transform:uppercase;
 letter-spacing:.06em;color:var(--text-muted);padding:8px 10px;border-bottom:1px solid var(--line)}
td{padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:none}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;
 vertical-align:-1px;box-shadow:0 0 0 2px var(--surface-1)}
.card{background:var(--surface-2);border:1px solid var(--line);border-radius:12px;
 padding:18px 20px;margin:0 0 14px;scroll-margin-top:20px}
.who{color:var(--text-secondary);font-size:13px;margin:0 0 14px}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin:0 0 20px;font-size:12.5px;color:var(--text-secondary)}
.note{background:var(--surface-2);border:1px solid var(--line);border-left:3px solid var(--s3);
 border-radius:8px;padding:12px 15px;font-size:13px;color:var(--text-secondary);margin:14px 0}
.cem{color:var(--s1);font-weight:600}
.mut{color:var(--text-muted)}
.num{font-variant-numeric:tabular-nums}
a{color:var(--s0)}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:0 0 18px}
input[type=search],select{font:inherit;background:var(--surface-1);color:var(--text-primary);
 border:1px solid var(--line);border-radius:8px;padding:6px 10px}
:target{outline:2px solid var(--s0);outline-offset:3px}
@media print{.card{break-inside:avoid}body{background:#fff}.toolbar{display:none}}
"""


def esc(s) -> str:
    return html.escape("" if s is None else str(s))


def slot_var(event_type: str) -> str:
    return f"var(--s{EVENT_SLOT.get(event_type, 3)})"


def legend(event_types=None) -> str:
    types = event_types or EVENT_ORDER
    return '<div class="legend">' + "".join(
        f'<span><span class="dot" style="background:{slot_var(t)}"></span>{esc(t)}</span>'
        for t in types) + "</div>"


def page(title: str, body: str, extra_css: str = "", extra_head: str = "") -> str:
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><style>{CSS}{extra_css}</style>{extra_head}</head>'
            f'<body><div class="wrap">{body}</div></body></html>')


def write_page(path: Path, title: str, body: str, extra_css: str = "", extra_head: str = "") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page(title, body, extra_css, extra_head), encoding="utf-8")
    return path


def place_anchor(place_key: str) -> str:
    """Stable HTML anchor id for a place -- the hook the map links into."""
    import re as _re
    return "loc-" + _re.sub(r"[^a-z0-9]+", "-", (place_key or "").lower()).strip("-")
