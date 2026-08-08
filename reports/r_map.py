#!/usr/bin/env python3
"""
reports/r_map.py
----------------
The research map.

Worldwide Leaflet map over OpenStreetMap tiles. Two things drove this rewrite:

  * The tree is no longer confined to a few US states, so a bundled state-outline
    SVG is not an option -- ancestors here sit in twelve countries.
  * Clicking a pin previously opened a side panel that collapsed off-screen on
    narrow windows, so the detail was effectively unreadable. Now every pin links
    straight into that place's card in the Locations report, which carries the
    fuller record anyway. The inline panel stays for quick scanning; the link is
    where you go for the real detail.

The place -> anchor mapping is read from `place_anchors.json`, published by the
Locations report, rather than recomputed here -- anchors get de-duplicated over
there and guessing them would silently produce dead links.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from .base import Report, Param, RunSpec, Artifact, html_artifact, P_MAX_GENS, P_YEAR_MIN, P_YEAR_MAX
from .theme import CSS, esc, MAP_CATEGORY, place_anchor

CAT_LABEL = {
    "cemetery": "Burial",
    "vital": "Birth / death / marriage",
    "residence": "Residence / census / other",
}


def _load_anchor_map(spec: RunSpec) -> dict:
    """PlaceKey -> anchor id, as published by the Locations report."""
    for cand in (spec.out_dir.parent / "locations" / "place_anchors.json",
                 spec.out_dir / "place_anchors.json"):
        try:
            if cand.exists():
                return json.loads(cand.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _filtered(rows, spec: RunSpec):
    ymin, ymax = spec.p("year_min"), spec.p("year_max")
    ymin = int(ymin) if ymin else None
    ymax = int(ymax) if ymax else None
    out = []
    for r in rows:
        if not r.get("Lat") or not r.get("Lon"):
            continue
        y = r.get("Year")
        y = int(y) if str(y).strip().isdigit() else None
        if y is not None:
            if ymin is not None and y < ymin:
                continue
            if ymax is not None and y > ymax:
                continue
        out.append(r)
    return out


def run(spec: RunSpec) -> list:
    rows = _filtered(spec.pipeline.event_rows, spec)
    anchors = _load_anchor_map(spec)
    has_locations = bool(anchors)

    by_place = defaultdict(list)
    for r in rows:
        by_place[r["PlaceKey"] or r["PlaceLabel"]].append(r)

    places = []
    for key, evs in by_place.items():
        years = [int(e["Year"]) for e in evs if str(e.get("Year", "")).strip().isdigit()]
        cems = sorted({e["Cemetery"] for e in evs if e.get("Cemetery")})
        cem_detail = []
        for c in cems:
            bits = sorted({(e.get("CemeteryAddress") or "", e.get("CemeteryPlot") or "")
                           for e in evs if e.get("Cemetery") == c})
            cem_detail.append({"name": c,
                               "detail": " \u00b7 ".join(x for t in bits for x in t if x)})
        cats = Counter(MAP_CATEGORY.get(e["Event"], "residence") for e in evs)
        has_burial = any(e["Tag"] == "BURI" for e in evs)
        places.append({
            "key": key,
            "label": evs[0]["PlaceLabel"] or evs[0]["PlaceRaw"],
            "country": evs[0].get("Country") or "Unknown",
            "lat": float(evs[0]["Lat"]), "lon": float(evs[0]["Lon"]),
            "prec": evs[0].get("GeoPrecision") or "", "src": evs[0].get("GeoSource") or "",
            "anchor": anchors.get(key) or place_anchor(key),
            "y0": min(years) if years else None, "y1": max(years) if years else None,
            "cem": cem_detail, "burial": has_burial,
            "cat": "cemetery" if has_burial else (cats.most_common(1)[0][0] if cats else "residence"),
            "n": len(evs), "np": len({e["PersonID"] for e in evs}),
            "events": sorted(
                [{"person": e["PersonName"], "rel": e["Relationship"], "line": e["Line"],
                  "event": e["Event"], "cat": MAP_CATEGORY.get(e["Event"], "residence"),
                  "date": e["Date"], "year": (int(e["Year"]) if str(e.get("Year", "")).strip().isdigit() else None),
                  "plot": e.get("CemeteryPlot") or ""}
                 for e in evs],
                key=lambda z: (z["year"] or 9999)),
        })
    places.sort(key=lambda p: (not p["burial"], -p["np"], -p["n"]))

    years_all = [int(r["Year"]) for r in rows if str(r.get("Year", "")).strip().isdigit()]
    y0, y1 = (min(years_all), max(years_all)) if years_all else (1500, 2025)
    countries = sorted({p["country"] for p in places})
    people = sorted({r["PersonName"] for r in rows})

    total_events = len(rows)
    unmapped = sum(1 for r in spec.pipeline.event_rows if not r.get("Lat"))

    out = spec.out_dir / "map.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_render(places=places, y0=y0, y1=y1, countries=countries, people=people,
                           target=spec.target_name, total_events=total_events,
                           unmapped=unmapped, has_locations=has_locations),
                   encoding="utf-8")

    arts = [html_artifact(out, "Research map",
                          note=("Click any marker for who was there and when; the link in the "
                                "panel opens that place's full entry in the Locations report."
                                if has_locations else
                                "Run the Locations report alongside this one to enable "
                                "click-through to full place detail."))]
    return arts


def _render(*, places, y0, y1, countries, people, target, total_events, unmapped, has_locations) -> str:
    data = json.dumps(places, separators=(",", ":"))
    country_opts = "".join(f"<option>{esc(c)}</option>" for c in countries)
    people_opts = "".join(f"<option>{esc(p)}</option>" for p in people)
    link_note = ("" if has_locations else
                 '<p class="warnbar">The Locations report was not generated for this run, so '
                 'the &ldquo;full detail&rdquo; links are disabled. Tick Locations next time to enable them.</p>')
    unmapped_note = (f'<p class="warnbar">{unmapped} event(s) could not be placed on the map because '
                     f'their location could not be resolved to coordinates. They are still listed in '
                     f'the Timelines and Locations reports.</p>' if unmapped else "")

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Research map &middot; {esc(target)}</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/leaflet.markercluster.min.js"></script>
<style>{CSS}
html,body{{height:100%;margin:0}}
body{{display:flex;flex-direction:column;overflow:hidden}}
header{{padding:14px 22px 10px;border-bottom:1px solid var(--line);flex:none}}
header h1{{font-size:19px;margin:0 0 3px}}
.bar{{display:flex;flex-wrap:wrap;gap:14px;align-items:center;padding:10px 22px;
 border-bottom:1px solid var(--line);background:var(--surface-2);font-size:12.5px;flex:none}}
.grp{{display:flex;gap:8px;align-items:center}}
.cap{{color:var(--text-muted);font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;font-weight:600}}
.grp label{{display:flex;gap:5px;align-items:center;cursor:pointer;color:var(--text-secondary)}}
.sw{{width:11px;height:11px;border-radius:50%;box-shadow:0 0 0 2px var(--surface-2)}}
input[type=number]{{width:76px;font:inherit;background:var(--surface-1);color:var(--text-primary);
 border:1px solid var(--line);border-radius:7px;padding:4px 7px}}
.count{{margin-left:auto;color:var(--text-muted);font-variant-numeric:tabular-nums}}
main{{flex:1;display:flex;min-height:0}}
#map{{flex:1;min-width:0;background:var(--surface-2)}}
aside{{width:352px;flex:none;border-left:1px solid var(--line);overflow:auto;padding:18px 20px;background:var(--surface-1)}}
aside h2{{margin:0 0 3px;font-size:16px}}
.pm{{color:var(--text-secondary);font-size:12px;margin:0 0 12px}}
.golink{{display:inline-block;margin:2px 0 14px;padding:7px 12px;border-radius:8px;
 background:var(--s0);color:#fff;text-decoration:none;font-size:12.5px;font-weight:600}}
.golink[aria-disabled=true]{{background:var(--surface-3);color:var(--text-muted);pointer-events:none}}
.cemn{{color:var(--cemetery);font-weight:600;font-size:13px;margin:0 0 2px}}
.cemd{{color:var(--text-secondary);font-size:11.5px;margin:0 0 10px}}
.row{{display:flex;gap:8px;padding:6px 0;border-top:1px solid var(--line)}}
.pdot{{width:8px;height:8px;border-radius:50%;flex:none;margin-top:5px}}
.yrc{{font-variant-numeric:tabular-nums;color:var(--text-muted);font-size:11.5px;flex:none;width:78px}}
.fin{{color:var(--text-muted);font-size:11.5px}}
.warn{{margin-top:12px;padding:9px 11px;border-radius:8px;background:var(--surface-2);
 border-left:3px solid var(--cemetery);color:var(--text-secondary);font-size:11.5px}}
.warnbar{{margin:0;padding:8px 22px;background:var(--surface-2);border-bottom:1px solid var(--line);
 color:var(--text-secondary);font-size:12px}}
.leaflet-popup-content{{margin:10px 12px;font:13px/1.45 inherit}}
@media(max-width:900px){{main{{flex-direction:column}}aside{{width:auto;border-left:none;
 border-top:1px solid var(--line);max-height:46%}}}}
</style></head><body>
<header><h1>Research map</h1>
<p class="sub" style="margin:0">Ancestors of {esc(target)} &middot; {total_events} located events &middot; {len(places)} places in {len(countries)} countries</p></header>
{link_note}{unmapped_note}
<div class="bar">
 <div class="grp"><span class="cap">Show</span>
  <label><input type="checkbox" class="cat" value="cemetery" checked><span class="sw" style="background:var(--cemetery)"></span>Burial</label>
  <label><input type="checkbox" class="cat" value="vital" checked><span class="sw" style="background:var(--vital)"></span>Birth / death / marriage</label>
  <label><input type="checkbox" class="cat" value="residence" checked><span class="sw" style="background:var(--residence)"></span>Residence / census</label></div>
 <div class="grp"><span class="cap">Line</span><select id="line">
  <option value="">All</option><option value="paternal">Paternal</option><option value="maternal">Maternal</option></select></div>
 <div class="grp"><span class="cap">Country</span><select id="country"><option value="">All</option>{country_opts}</select></div>
 <div class="grp"><span class="cap">Person</span><select id="person"><option value="">Everyone</option>{people_opts}</select></div>
 <div class="grp"><span class="cap">Years</span>
  <input type="number" id="ymin" value="{y0}" min="{y0}" max="{y1}" step="1">
  <span class="mut">to</span>
  <input type="number" id="ymax" value="{y1}" min="{y0}" max="{y1}" step="1"></div>
 <div class="count" id="count"></div></div>
<main><div id="map"></div>
<aside id="panel"><h2>Select a place</h2>
<p class="pm">Click any marker to see who was there and when. Bigger markers mean more recorded
events; an orange marker means a burial is recorded there.</p></aside></main>
<script>
const DATA={data}, HAS_LOC={str(has_locations).lower()};
const COL={{vital:'--vital',cemetery:'--cemetery',residence:'--residence'}};
const cv=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
const map=L.map('map',{{worldCopyJump:true}}).setView([40,-40],3);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
 {{attribution:'&copy; OpenStreetMap contributors',maxZoom:19}}).addTo(map);
const cluster=L.markerClusterGroup({{maxClusterRadius:44,showCoverageOnHover:false}});
map.addLayer(cluster);
const panel=document.getElementById('panel');
let sel=null;

function current(){{
 const cats=[...document.querySelectorAll('.cat:checked')].map(c=>c.value);
 const line=document.getElementById('line').value;
 const country=document.getElementById('country').value;
 const person=document.getElementById('person').value;
 const a=parseInt(document.getElementById('ymin').value,10);
 const b=parseInt(document.getElementById('ymax').value,10);
 const lo=isNaN(a)?-9999:a, hi=isNaN(b)?9999:b;
 const out=[];
 for(const p of DATA){{
  if(country&&p.country!==country)continue;
  const evs=p.events.filter(e=>cats.includes(e.cat)&&(!line||e.line===line)&&
    (!person||e.person===person)&&(e.year==null||(e.year>=lo&&e.year<=hi)));
  if(evs.length)out.push({{p,evs}});
 }}
 return out;
}}
function draw(){{
 cluster.clearLayers();
 const vis=current(); let n=0;
 for(const {{p,evs}} of vis){{
  n+=evs.length;
  const isC=evs.some(e=>e.cat==='cemetery');
  const cat=isC?'cemetery':evs[0].cat;
  const r=Math.max(7,Math.min(20,5+Math.sqrt(evs.length)*3));
  const m=L.circleMarker([p.lat,p.lon],{{radius:r,fillColor:cv(COL[cat]),fillOpacity:.85,
    color:cv('--surface-1'),weight:2}});
  m.bindTooltip(p.label+' \\u00b7 '+evs.length,{{direction:'top'}});
  m.on('click',()=>show(p,evs));
  cluster.addLayer(m);
 }}
 document.getElementById('count').textContent=vis.length+' places \\u00b7 '+n+' events';
 if(sel){{const m=vis.find(o=>o.p.key===sel); m?show(m.p,m.evs,true):reset();}}
}}
function reset(){{sel=null;panel.innerHTML='<h2>Select a place</h2><p class="pm">Click any marker to see who was there and when.</p>';}}
function show(p,evs,keep){{
 sel=p.key;
 let h='<h2>'+esc(p.label)+'</h2><p class="pm">'+p.np+(p.np==1?' person':' people')+
   ' \\u00b7 '+evs.length+' of '+p.n+' events';
 if(p.y0)h+=' \\u00b7 '+p.y0+(p.y1!=p.y0?'\\u2013'+p.y1:'');
 h+='</p>';
 const href='../locations/locations.html#'+p.anchor;
 h+=HAS_LOC?('<a class="golink" href="'+href+'" target="_blank" rel="noopener">Open full detail in Locations \\u2192</a>')
           :('<span class="golink" aria-disabled="true">Locations report not generated</span>');
 for(const c of p.cem){{h+='<p class="cemn">\\u2691 '+esc(c.name)+'</p>';if(c.detail)h+='<p class="cemd">'+esc(c.detail)+'</p>';}}
 for(const e of evs)h+='<div class="row"><span class="pdot" style="background:'+cv(COL[e.cat])+'"></span>'+
   '<span class="yrc">'+esc(e.date||'undated')+'</span><span><b>'+esc(e.person)+'</b> \\u2014 '+esc(e.event)+
   '<br><span class="fin">'+esc(e.rel)+(e.plot?' \\u00b7 '+esc(e.plot):'')+'</span></span></div>';
 h+='<p class="fin" style="margin-top:12px">'+p.lat.toFixed(4)+', '+p.lon.toFixed(4)+'</p>';
 if((p.prec||'').indexOf('county')>=0||(p.prec||'').indexOf('nearest')>=0)
   h+='<p class="warn">This pin is approximate \\u2014 '+esc(p.prec)+'. Confirm the exact address before travelling.</p>';
 panel.innerHTML=h; if(!keep)panel.scrollTop=0;
}}
function fit(){{
 const vis=current(); if(!vis.length)return;
 map.fitBounds(L.latLngBounds(vis.map(o=>[o.p.lat,o.p.lon])).pad(.15));
}}
document.querySelectorAll('.cat').forEach(c=>c.addEventListener('change',draw));
['line','country','person','ymin','ymax'].forEach(i=>document.getElementById(i).addEventListener('input',draw));
document.getElementById('country').addEventListener('change',()=>{{draw();fit();}});
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',draw);
draw(); fit();
</script></body></html>"""


REPORT = Report(
    id="map",
    title="Research map",
    description=("Every located event plotted on a worldwide map, clustered by area and filterable "
                 "by family line, country, person and date range. Click a marker to see who was "
                 "there and when, then jump straight to that place's full entry in Locations."),
    run=run,
    params=[P_MAX_GENS, P_YEAR_MIN, P_YEAR_MAX],
    needs_events=True,
    needs_target=True,
    requires=["locations"],
    order=30,
)
