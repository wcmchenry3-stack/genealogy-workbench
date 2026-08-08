#!/usr/bin/env python3
"""
reports/r_map_classic.py
-------------------------
The original hand-drawn research map, generalised to any US states.

This is "Report 3, first version" -- the self-contained SVG map that predates
the Leaflet rewrite in `r_map.py`. It draws real county polygons (not just
points on a tile basemap), pans and zooms with no network connection, and
prints cleanly. It was retired because the first version baked in county
geometry for exactly three hardcoded states (Ohio, Michigan, West Virginia)
-- a tree that grows into England or the Czech Republic simply has nowhere
to put those pins.

This version keeps everything that made the original worth keeping and fixes
the one thing that didn't generalise:

  * County geometry now comes from the `basemap-data` package's `UScounties`
    shapefile (public-domain, Census-derived, all 3,221 US counties) via
    `pyshp`, filtered at run time to whichever states actually have a dated
    event -- not a hardcoded three.
  * The Albers conic projection's standard parallels and central meridian are
    now derived from the actual bounding box of the selected states, instead
    of numbers tuned for a Ohio/Michigan/West Virginia cluster. A one-state
    tree and a coast-to-coast tree both project reasonably.
  * The Douglas-Peucker simplification tolerance scales with the projected
    bounding box, so a small cluster keeps fine detail and a wide one doesn't
    produce an oversized SVG.

What it still cannot do -- by construction, not oversight -- is draw anywhere
outside the United States. Non-US events, and US events whose place didn't
resolve to a state, are left off this map and counted in a banner at the top;
the worldwide map in `r_map.py` is what covers them. Both reports read the
same event rows, so picking whichever view suits the moment doesn't cost a
second GEDCOM pass.
"""
from __future__ import annotations

import importlib.util
import json
import math
from collections import defaultdict
from pathlib import Path

from .base import Artifact, Param, Report, RunSpec, P_MAX_GENS, P_YEAR_MIN, P_YEAR_MAX, html_artifact
from .theme import CSS, esc, MAP_CATEGORY, place_anchor, write_page

INSTALL_HINT = "pip install pyshp basemap-data"


def _load_anchor_map(spec: RunSpec) -> dict:
    """PlaceKey -> anchor id, as published by the Locations report. Same contract
    `r_map.py` reads; duplicated here rather than imported so each report module
    stays self-contained (see reports/base.py)."""
    for cand in (spec.out_dir.parent / "locations" / "place_anchors.json",
                 spec.out_dir / "place_anchors.json"):
        try:
            if cand.exists():
                return json.loads(cand.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _shapefile_base() -> Path | None:
    """Path (no extension) to UScounties.shp/.shx/.dbf inside basemap-data, or
    None if the optional dependency isn't installed."""
    spec = importlib.util.find_spec("mpl_toolkits.basemap_data")
    if spec is None or not spec.submodule_search_locations:
        return None
    base = Path(list(spec.submodule_search_locations)[0]) / "UScounties"
    return base if base.with_suffix(".shp").exists() else None


def _missing_dependency_artifact(spec: RunSpec) -> Artifact:
    out = spec.out_dir / "map_classic.html"
    body = ('<h1>Research map (classic)</h1>'
           f'<div class="note">This report draws real US county shapes offline, which needs two extra '
           f'packages: <code>pyshp</code> and <code>basemap-data</code> (a public-domain county boundary '
           f'dataset, ~30&nbsp;MB). Install them with <code>{esc(INSTALL_HINT)}</code> -- both are already '
           f'listed in requirements.txt -- and run this report again.</div>')
    write_page(out, "Research map (classic)", body)
    return html_artifact(out, "Research map (classic)",
                         note="Missing dependency: run `pip install pyshp basemap-data`.")


def _simplify(pts: list, tol: float) -> list:
    """Douglas-Peucker on an open polyline."""
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1e-12
    idx, dmax = 0, 0.0
    for i in range(1, len(pts) - 1):
        p = pts[i]
        d = abs(dy * p[0] - dx * p[1] + b[0] * a[1] - b[1] * a[0]) / length
        if d > dmax:
            idx, dmax = i, d
    if dmax > tol:
        return _simplify(pts[:idx + 1], tol)[:-1] + _simplify(pts[idx:], tol)
    return [a, b]


def _simplify_ring(pts: list, tol: float) -> list:
    """Douglas-Peucker on a closed ring.

    A ring's first and last point coincide, which makes the perpendicular
    distance to the closing chord identically zero and collapses the whole
    ring to two points. Split it into two open chains and simplify each.
    """
    closed = len(pts) > 2 and pts[0] == pts[-1]
    body = pts[:-1] if closed else pts
    if len(body) < 4:
        return pts
    h = len(body) // 2
    out = _simplify(body[:h + 1], tol)[:-1] + _simplify(body[h:], tol)
    if closed:
        out = out + [out[0]]
    return out


def _filtered(rows, spec: RunSpec):
    """US, geocoded, in-range rows for the map, plus a count of rows this
    report structurally can't place (no coordinates, not the US, or a US
    place that didn't resolve to a state)."""
    ymin, ymax = spec.p("year_min"), spec.p("year_max")
    ymin = int(ymin) if ymin else None
    ymax = int(ymax) if ymax else None
    us_rows, excluded = [], 0
    for r in rows:
        if not r.get("Lat") or not r.get("Lon"):
            excluded += 1
            continue
        y = r.get("Year")
        y = int(y) if str(y).strip().isdigit() else None
        if y is not None:
            if ymin is not None and y < ymin:
                continue
            if ymax is not None and y > ymax:
                continue
        if r.get("CountryCode") != "US" or not r.get("RegionCode"):
            excluded += 1
            continue
        us_rows.append(r)
    return us_rows, excluded


def run(spec: RunSpec) -> list[Artifact]:
    shp_base = _shapefile_base()
    if shp_base is None:
        return [_missing_dependency_artifact(spec)]
    import shapefile  # deferred: only needed once we know the dependency is present

    rows, excluded = _filtered(spec.pipeline.event_rows, spec)
    anchors = _load_anchor_map(spec)
    has_locations = bool(anchors)

    out = spec.out_dir / "map_classic.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    title = f"Research map (classic) — {spec.target_name}"

    if not rows:
        body = (f'<h1>Research map (classic)</h1>'
               f'<p class="sub">Every located US event for {esc(spec.target_name)} and ancestors, drawn on '
               f'real county shapes.</p>'
               f'<div class="note">No US events with a resolved state matched the current filters '
               f'(year range, or the tree simply has no US places). The worldwide map covers everywhere '
               f'else.</div>')
        write_page(out, title, body)
        return [html_artifact(out, "Research map (classic)", note="No US places matched the filters.")]

    # ---- group rows into places, same shape as r_map.py's payload -------
    by_place = defaultdict(list)
    for r in rows:
        by_place[r["PlaceKey"] or r["PlaceLabel"]].append(r)

    state_names: dict[str, str] = {}
    places = []
    for key, evs in by_place.items():
        years = [int(e["Year"]) for e in evs if str(e.get("Year", "")).strip().isdigit()]
        cems = sorted({e["Cemetery"] for e in evs if e.get("Cemetery")})
        cem_detail = []
        for c in cems:
            bits = sorted({(e.get("CemeteryAddress") or "", e.get("CemeteryPlot") or "")
                           for e in evs if e.get("Cemetery") == c})
            cem_detail.append({"name": c, "detail": " \u00b7 ".join(x for t in bits for x in t if x)})
        state = evs[0]["RegionCode"]
        state_names[state] = evs[0].get("Region") or state
        has_burial = any(e.get("Tag") == "BURI" for e in evs)
        places.append({
            "key": key, "label": evs[0]["PlaceLabel"] or evs[0]["PlaceRaw"],
            "state": state, "county": (evs[0].get("Subregion") or ""),
            "lat": float(evs[0]["Lat"]), "lon": float(evs[0]["Lon"]),
            "prec": evs[0].get("GeoPrecision") or "",
            "anchor": anchors.get(key) or place_anchor(key),
            "y0": min(years) if years else None, "y1": max(years) if years else None,
            "cem": cem_detail, "burial": has_burial,
            "n": len(evs), "np": len({e["PersonID"] for e in evs}),
            "events": sorted(
                [{"person": e["PersonName"], "rel": e["Relationship"], "line": e["Line"],
                  "event": e["Event"], "cat": MAP_CATEGORY.get(e["Event"], "residence"),
                  "date": e["Date"], "year": (int(e["Year"]) if str(e.get("Year", "")).strip().isdigit() else None),
                  "plot": e.get("CemeteryPlot") or ""}
                 for e in evs],
                key=lambda z: (z["year"] if z["year"] is not None else 9999)),
        })
    places.sort(key=lambda p: (not p["burial"], -p["np"], -p["n"]))

    states = sorted(state_names)

    # ---- geometry: read only the counties for states actually in play ---
    r = shapefile.Reader(str(shp_base), encoding="latin-1")
    field_names = [f[0] for f in r.fields[1:]]
    i_state, i_name = field_names.index("STATE"), field_names.index("NAME")

    raw_counties = []
    lat_min = lat_max = lon_min = lon_max = None
    for i in range(len(r)):
        rec = r.record(i)
        if rec[i_state] not in states:
            continue
        shp = r.shape(i)
        parts = list(shp.parts) + [len(shp.points)]
        rings = [shp.points[a:b] for a, b in zip(parts, parts[1:])]
        for ring in rings:
            for lon, lat in ring:
                lat_min = lat if lat_min is None else min(lat_min, lat)
                lat_max = lat if lat_max is None else max(lat_max, lat)
                lon_min = lon if lon_min is None else min(lon_min, lon)
                lon_max = lon if lon_max is None else max(lon_max, lon)
        raw_counties.append({"st": rec[i_state], "nm": rec[i_name], "rings": rings})

    # ---- Albers conic, fit to the actual bounding box, not a fixed region ----
    # Standard parallels at the classic "1/6 rule" positions inside the latitude
    # span; central meridian at the mid-longitude. A single-point span (one town,
    # one state) gets a small floor so the projection doesn't divide by zero.
    lat_span = max(lat_max - lat_min, 0.5)
    lon_mid = (lon_min + lon_max) / 2
    p1 = math.radians(lat_min + lat_span / 6)
    p2 = math.radians(lat_max - lat_span / 6)
    if abs(p2 - p1) < 1e-9:
        p2 += math.radians(0.5)
    p0 = math.radians((lat_min + lat_max) / 2)
    l0 = math.radians(lon_mid)
    n = (math.sin(p1) + math.sin(p2)) / 2
    c = math.cos(p1) ** 2 + 2 * n * math.sin(p1)
    r0 = math.sqrt(c - 2 * n * math.sin(p0)) / n

    def proj(lon: float, lat: float) -> tuple[float, float]:
        t = n * (math.radians(lon) - l0)
        rr = math.sqrt(max(c - 2 * n * math.sin(math.radians(lat)), 0)) / n
        return rr * math.sin(t), r0 - rr * math.cos(t)

    # Tolerance scales with the projected bounding box: a tight cluster of
    # counties keeps fine detail, a coast-to-coast spread simplifies harder so
    # the SVG doesn't balloon.
    px0, py0 = proj(lon_min, lat_min)
    px1, py1 = proj(lon_max, lat_max)
    span = max(abs(px1 - px0), abs(py1 - py0)) or 1e-6
    tol = span / 4500

    counties = []
    for county in raw_counties:
        rings = []
        for ring in county["rings"]:
            pts = [proj(x, y) for x, y in ring]
            if len(pts) > 3:
                pts = _simplify_ring(pts, tol)
            if len(pts) > 2:
                rings.append(pts)
        if rings:
            counties.append({"st": county["st"], "nm": county["nm"], "rings": rings})

    xs = [p[0] for cty in counties for ring in cty["rings"] for p in ring]
    ys = [p[1] for cty in counties for ring in cty["rings"] for p in ring]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w = 1000.0
    h = 1000.0 * (y1 - y0) / (x1 - x0) if x1 != x0 else 1000.0
    pad = 10.0

    def sx(x: float) -> float:
        return pad + (x - x0) / (x1 - x0) * (w - 2 * pad)

    def sy(y: float) -> float:
        return pad + (y1 - y) / (y1 - y0) * (h - 2 * pad)

    def path_of(rings: list) -> str:
        return "".join("M" + "L".join(f"{sx(x):.1f} {sy(y):.1f}" for x, y in ring) + "Z" for ring in rings)

    hot = {(p["state"], p["county"].strip().casefold()) for p in places if p["county"]}
    county_svg = "".join(
        f'<path d="{path_of(cty["rings"])}" class="cty'
        f'{" hot" if (cty["st"], cty["nm"].strip().casefold()) in hot else ""}">'
        f'<title>{esc(cty["nm"])} County, {esc(cty["st"])}</title></path>' for cty in counties)

    # County rings are still in *projected* (Albers) space here, not yet scaled
    # into the 0..1000 SVG viewBox -- the label position has to go through
    # sx()/sy() exactly like every county path point does, or it lands near
    # the SVG origin instead of over the state.
    state_labels = []
    for st in states:
        st_counties = [c for c in counties if c["st"] == st]
        if not st_counties:
            continue
        proj_xs = [p[0] for c in st_counties for ring in c["rings"] for p in ring]
        proj_ys = [p[1] for c in st_counties for ring in c["rings"] for p in ring]
        cx, cy = (min(proj_xs) + max(proj_xs)) / 2, (min(proj_ys) + max(proj_ys)) / 2
        state_labels.append(f'<text class="stl" x="{sx(cx):.0f}" y="{sy(cy):.0f}">'
                            f'{esc(state_names[st])}</text>')

    for p in places:
        x, y = proj(p["lon"], p["lat"])
        p["x"], p["y"] = round(sx(x), 1), round(sy(y), 1)

    people = sorted({e["person"] for p in places for e in p["events"]})
    years_all = [e["year"] for p in places for e in p["events"] if e["year"] is not None]
    y_lo, y_hi = (min(years_all), max(years_all)) if years_all else (1500, 2025)
    total_events = sum(p["n"] for p in places)

    excluded_note = (f'<p class="note" style="margin:0;border-radius:0;border-left:none;'
                     f'border-bottom:3px solid var(--s3)">{excluded} event(s) are not shown on this map '
                     f'-- either outside the United States or without coordinates. The worldwide map '
                     f'covers those.</p>' if excluded else "")
    link_note = ("" if has_locations else
                '<p class="note" style="margin:0;border-radius:0;border-left:none;'
                'border-bottom:3px solid var(--s3)">The Locations report was not generated for this run, '
                'so the &ldquo;full detail&rdquo; links are disabled. Tick Locations next time to enable '
                'them.</p>')

    state_list = ", ".join(state_names[s] for s in states)
    html = _render(
        target=spec.target_name, people_count=len({e["person"] for p in places for e in p["events"]}),
        total_events=total_events, place_count=len(places), state_list=state_list,
        county_svg=county_svg, state_labels="".join(state_labels), w=w, h=h,
        people=people, y_lo=y_lo, y_hi=y_hi, places=places, has_locations=has_locations,
        excluded_note=excluded_note, link_note=link_note,
    )
    out.write_text(html, encoding="utf-8")

    return [html_artifact(out, "Research map (classic)",
                          note=(f"{len(places)} places across {len(states)} state"
                                f"{'s' if len(states) != 1 else ''} \u00b7 offline, no tiles"))]


def _render(*, target, people_count, total_events, place_count, state_list, county_svg, state_labels,
           w, h, people, y_lo, y_hi, places, has_locations, excluded_note, link_note) -> str:
    data = json.dumps(places, separators=(",", ":"))
    people_opts = "".join(f"<option>{esc(p)}</option>" for p in people)
    href_base = "../locations/locations.html#" if has_locations else ""

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Research map (classic) &middot; {esc(target)}</title>
<style>{CSS}
:root{{--land:#e7e6df;--landhot:#d3dcea}}
@media (prefers-color-scheme:dark){{:root:where(:not([data-theme=light])){{--land:#2e2e2b;--landhot:#363d47}}}}
html,body{{height:100%;margin:0}}
body{{display:flex;flex-direction:column;overflow:hidden}}
header{{padding:14px 22px 10px;border-bottom:1px solid var(--line);flex:none}}
header h1{{font-size:19px;margin:0 0 3px}}
.bar{{display:flex;flex-wrap:wrap;gap:15px;align-items:center;padding:10px 22px;
 border-bottom:1px solid var(--line);background:var(--surface-2);font-size:12.5px;flex:none}}
.grp{{display:flex;gap:8px;align-items:center}}
.cap{{color:var(--text-muted);font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;font-weight:600}}
.grp label{{display:flex;gap:5px;align-items:center;cursor:pointer;color:var(--text-secondary)}}
.sw{{width:11px;height:11px;border-radius:50%;box-shadow:0 0 0 2px var(--surface-2)}}
input[type=range]{{accent-color:var(--vital);width:130px}}
.yr{{font-variant-numeric:tabular-nums;min-width:78px;color:var(--text-primary)}}
.count{{margin-left:auto;color:var(--text-muted);font-variant-numeric:tabular-nums}}
main{{flex:1;display:flex;min-height:0}}
#stage{{flex:1;position:relative;overflow:hidden;background:var(--surface-1)}}
svg{{width:100%;height:100%;display:block;cursor:grab}}
svg.drag{{cursor:grabbing}}
.cty{{fill:var(--land);stroke:var(--surface-1);stroke-width:.75}}
.cty.hot{{fill:var(--landhot)}}
.stl{{fill:var(--text-muted);font-size:15px;font-weight:600;text-anchor:middle;
 letter-spacing:.14em;text-transform:uppercase;opacity:.55;pointer-events:none}}
.pin{{cursor:pointer}}
.pin circle.core{{stroke:var(--surface-1);stroke-width:2}}
.ring{{fill:none;stroke:var(--cemetery);stroke-width:2;stroke-dasharray:3 3;opacity:.9;pointer-events:none}}
aside{{width:340px;flex:none;border-left:1px solid var(--line);overflow:auto;padding:18px 20px;background:var(--surface-1)}}
aside h2{{margin:0 0 3px;font-size:16px}}
aside .pm{{color:var(--text-secondary);font-size:12px;margin:0 0 12px}}
.golink{{display:inline-block;margin:2px 0 14px;padding:7px 12px;border-radius:8px;
 background:var(--s0);color:#fff;text-decoration:none;font-size:12.5px;font-weight:600}}
.golink[aria-disabled=true]{{background:var(--surface-3);color:var(--text-muted);pointer-events:none}}
.cemn{{color:var(--cemetery);font-weight:600;font-size:13px;margin:0 0 2px}}
.cemd{{color:var(--text-secondary);font-size:11.5px;margin:0 0 10px}}
.row{{display:flex;gap:8px;padding:6px 0;border-top:1px solid var(--line)}}
.dot{{width:8px;height:8px;border-radius:50%;flex:none;margin-top:5px}}
.yrc{{font-variant-numeric:tabular-nums;color:var(--text-muted);font-size:11.5px;flex:none;width:74px}}
.fin{{color:var(--text-muted);font-size:11.5px}}
.empty{{color:var(--text-muted);font-size:13px}}
.warn{{margin-top:12px;padding:9px 11px;border-radius:8px;background:var(--surface-2);
 border-left:3px solid var(--cemetery);color:var(--text-secondary);font-size:11.5px}}
.zoom{{position:absolute;right:12px;bottom:12px;display:flex;flex-direction:column;gap:5px}}
.zoom button{{width:30px;height:30px;font-size:16px;border:1px solid var(--line);
 background:var(--surface-1);color:var(--text-primary);border-radius:7px;cursor:pointer}}
@media(max-width:860px){{main{{flex-direction:column}}aside{{width:auto;border-left:none;
 border-top:1px solid var(--line);max-height:44%}}}}
</style></head><body>
<header><h1>Research map (classic) &middot; ancestors of {esc(target)}</h1>
<p class="sub">{people_count} people &middot; {total_events} located events &middot; {place_count} places in {esc(state_list)}</p></header>
{link_note}{excluded_note}
<div class="bar">
 <div class="grp"><span class="cap">Show</span>
  <label><input type="checkbox" class="cat" value="cemetery" checked><span class="sw" style="background:var(--cemetery)"></span>Burial</label>
  <label><input type="checkbox" class="cat" value="vital" checked><span class="sw" style="background:var(--vital)"></span>Birth / death / marriage</label>
  <label><input type="checkbox" class="cat" value="residence" checked><span class="sw" style="background:var(--residence)"></span>Residence / census</label></div>
 <div class="grp"><span class="cap">Line</span><select id="line"><option value="">All</option>
  <option value="paternal">Paternal</option><option value="maternal">Maternal</option></select></div>
 <div class="grp"><span class="cap">Person</span><select id="person"><option value="">Everyone</option>{people_opts}</select></div>
 <div class="grp"><span class="cap">Through</span><input type="range" id="yr" min="{y_lo}" max="{y_hi}" value="{y_hi}">
  <span class="yr" id="yrl">{y_lo}&ndash;{y_hi}</span></div>
 <div class="count" id="count"></div></div>
<main><div id="stage">
 <svg id="map" viewBox="0 0 {w:.0f} {h:.0f}" role="img" aria-label="Map of {esc(state_list)} showing ancestral locations">
  <g id="pan"><g>{county_svg}{state_labels}</g><g id="pins"></g></g></svg>
 <div class="zoom"><button id="zi" title="Zoom in">+</button><button id="zo" title="Zoom out">&minus;</button><button id="zr" title="Fit to places">&#8853;</button><button id="za" title="Show every state drawn">&#9974;</button></div>
</div>
<aside id="panel"><h2>Select a place</h2>
 <p class="pm">Click any marker to see who was there and when. Larger markers mean more recorded
 events; a dashed ring marks a place with a burial.</p></aside></main>
<script>
const DATA={data}, HAS_LOC={str(has_locations).lower()};
const CV=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const COL={{vital:'--vital',cemetery:'--cemetery',residence:'--residence'}};
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
const pins=document.getElementById('pins'),panel=document.getElementById('panel');
let sel=null;

function visible(){{
 const cats=[...document.querySelectorAll('.cat:checked')].map(c=>c.value);
 const line=document.getElementById('line').value,per=document.getElementById('person').value;
 const yr=+document.getElementById('yr').value;
 document.getElementById('yrl').textContent={y_lo}+'\\u2013'+yr;
 return DATA.map(p=>({{p,evs:p.events.filter(e=>cats.includes(e.cat)&&(!line||e.line===line)&&
   (!per||e.person===per)&&(e.year==null||e.year<=yr))}})).filter(o=>o.evs.length);
}}
function draw(){{
 const vis=visible();pins.innerHTML='';
 let n=0;
 for(const {{p,evs}} of vis){{
  n+=evs.length;
  const isC=evs.some(e=>e.cat==='cemetery');
  const cat=isC?'cemetery':evs[0].cat;
  const r=Math.max(4.5,Math.min(13,3+Math.sqrt(evs.length)*2.1));
  const g=document.createElementNS('http://www.w3.org/2000/svg','g');
  g.setAttribute('class','pin');
  if(isC)g.innerHTML=`<circle class="ring" cx="${{p.x}}" cy="${{p.y}}" r="${{r+3.5}}"/>`;
  g.innerHTML+=`<circle class="core" cx="${{p.x}}" cy="${{p.y}}" r="${{r}}" fill="${{CV(COL[cat])}}" fill-opacity=".88"/>`;
  g.addEventListener('click',ev=>{{ev.stopPropagation();show(p,evs);}});
  const t=document.createElementNS('http://www.w3.org/2000/svg','title');
  t.textContent=p.label+' — '+evs.length+' event'+(evs.length>1?'s':'');
  g.appendChild(t);pins.appendChild(g);
 }}
 document.getElementById('count').textContent=vis.length+' places · '+n+' events';
 if(sel){{const m=vis.find(o=>o.p.key===sel);m?show(m.p,m.evs,true):clearPanel();}}
}}
function clearPanel(){{sel=null;panel.innerHTML='<h2>Select a place</h2><p class="pm">Click any marker to see who was there and when.</p>';}}
function show(p,evs,keep){{
 sel=p.key;
 let h=`<h2>${{esc(p.label)}}</h2><p class="pm">${{p.np}} ${{p.np==1?'person':'people'}} · ${{evs.length}} of ${{p.n}} events`;
 if(p.y0)h+=` · ${{p.y0}}${{p.y1!=p.y0?'\\u2013'+p.y1:''}}`;
 h+='</p>';
 const href='{href_base}'+p.anchor;
 h+=HAS_LOC?(`<a class="golink" href="${{href}}" target="_blank" rel="noopener">Open full detail in Locations \\u2192</a>`)
           :('<span class="golink" aria-disabled="true">Locations report not generated</span>');
 for(const c of p.cem){{h+=`<p class="cemn">\\u2691 ${{esc(c.name)}}</p>`;if(c.detail)h+=`<p class="cemd">${{esc(c.detail)}}</p>`;}}
 for(const e of evs)h+=`<div class="row"><span class="dot" style="background:${{CV(COL[e.cat])}}"></span>`+
  `<span class="yrc">${{esc(e.date||'undated')}}</span><span><b>${{esc(e.person)}}</b> — ${{esc(e.event)}}`+
  `<br><span class="fin">${{esc(e.rel)}}${{e.plot?' · '+esc(e.plot):''}}</span></span></div>`;
 h+=`<p class="fin" style="margin-top:12px">${{p.lat.toFixed(4)}}, ${{p.lon.toFixed(4)}}</p>`;
 if((p.prec||'').indexOf('county')>=0)h+=`<p class="warn">This pin sits at the county centroid — ${{esc(p.label)}} is too small for the coordinate gazetteer. Confirm the exact address before you drive.</p>`;
 panel.innerHTML=h;if(!keep)panel.scrollTop=0;
}}
// pan + zoom
const svg=document.getElementById('map'),pan=document.getElementById('pan');
let k=1,tx=0,ty=0,drag=null;
const apply=()=>pan.setAttribute('transform',`translate(${{tx}} ${{ty}}) scale(${{k}})`);
function zoom(f){{const cx={w / 2},cy={h / 2};tx=cx-(cx-tx)*f;ty=cy-(cy-ty)*f;k*=f;apply();}}
document.getElementById('zi').onclick=()=>zoom(1.4);
document.getElementById('zo').onclick=()=>zoom(1/1.4);
function fit(pins_only){{
 const b=svg.getBoundingClientRect(), ar=b.width/b.height;
 let x0,x1,y0,y1;
 if(pins_only){{
  const v=visible(); const P=v.length?v.map(o=>o.p):DATA;
  x0=Math.min(...P.map(p=>p.x));x1=Math.max(...P.map(p=>p.x));
  y0=Math.min(...P.map(p=>p.y));y1=Math.max(...P.map(p=>p.y));
  const mx=(x1-x0)*.12+18,my=(y1-y0)*.12+18;x0-=mx;x1+=mx;y0-=my;y1+=my;
 }} else {{x0=0;x1={w};y0=0;y1={h};}}
 const vw={w}, vh={h}, vAr=vw/vh;
 let sw=x1-x0, sh=y1-y0;
 if(sw/sh > (vAr>ar?vAr:ar)) sh=sw/(vAr>ar?vAr:ar); else sw=sh*(vAr>ar?vAr:ar);
 const cx=(x0+x1)/2, cy=(y0+y1)/2;
 if(ar>vAr) k=vh/sh; else k=vw/sw;
 tx=vw/2-cx*k; ty=vh/2-cy*k; apply();
}}
document.getElementById('zr').onclick=()=>fit(true);
document.getElementById('za').onclick=()=>fit(false);
svg.addEventListener('pointerdown',e=>{{drag={{x:e.clientX,y:e.clientY,tx,ty}};svg.classList.add('drag');svg.setPointerCapture(e.pointerId);}});
svg.addEventListener('pointermove',e=>{{if(!drag)return;const s={w}/svg.clientWidth;
 tx=drag.tx+(e.clientX-drag.x)*s;ty=drag.ty+(e.clientY-drag.y)*s;apply();}});
svg.addEventListener('pointerup',e=>{{drag=null;svg.classList.remove('drag');}});
svg.addEventListener('wheel',e=>{{e.preventDefault();zoom(e.deltaY<0?1.12:1/1.12);}},{{passive:false}});
svg.addEventListener('click',clearPanel);
document.querySelectorAll('.cat').forEach(c=>c.addEventListener('change',draw));
['line','person','yr'].forEach(i=>document.getElementById(i).addEventListener('input',draw));
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',draw);
draw();fit(true);
window.addEventListener('resize',()=>fit(true));
</script></body></html>"""


REPORT = Report(
    id="map_classic",
    title="Research map (classic)",
    description=("The original offline research map: real US county shapes drawn as SVG, pan/zoom, "
                 "no network connection needed, prints cleanly. Covers only US places with a resolved "
                 "state -- everywhere else is excluded with a note. See the worldwide map for full "
                 "coverage."),
    run=run,
    params=[P_MAX_GENS, P_YEAR_MIN, P_YEAR_MAX],
    needs_events=True,
    needs_target=True,
    requires=["locations"],
    group="Research",
    order=31,
)
