#!/usr/bin/env python3
"""
reports/r_locations.py
------------------------
The same events organised by place instead of by person, worldwide.

One card per distinct PlaceKey (country + region + subregion + locality --
see `core/places.PlaceRef.key`): who was there, when, what for, and whether
there is a cemetery to visit. Cards are ranked so the best research stops
come first -- a burial ground beats a residence, and a place that touches
many people beats one that touches few.

Every card gets `id="loc-..."` via `theme.place_anchor` so the map report can
deep-link straight into the readable detail here instead of cramming it into
a map popup.

Nothing here assumes the United States: places are grouped by whatever
`Country` the pipeline resolved, and region/subregion are simply blank for
the many places (most of the world) that do not have a US-style county.

Cards nest in a four-level hierarchy -- country, state/province, county,
then the card itself (city/town) -- with a header at each level that has
anything to show; levels with nothing to add (most of the world has no
county) are skipped rather than rendered empty. A matching set of native
multi-select filters lets a reader narrow to any combination of values at
each level; picking a country narrows which states/provinces are offered,
picking a state/province narrows the counties, and so on down to city.
"""
from __future__ import annotations

import csv as csvmod
from pathlib import Path

from .base import Artifact, Param, Report, RunSpec, P_MAX_GENS, P_YEAR_MAX, P_YEAR_MIN, csv_artifact, html_artifact
from .theme import esc, place_anchor, slot_var, write_page

P_COUNTRY = Param("country", "Country", "choice", "All",
                  "Limit the roster to one country. Leave as All to include everywhere.",
                  choices=None)

EXTRA_CSS = """
.place-country h2{margin-top:40px}
.plc-region{margin:0}
.plc-region>h3{margin:22px 0 10px 2px;padding-left:12px;border-left:3px solid var(--s0);font-size:16px}
.plc-subregion{margin:0}
.plc-subregion>h4{margin:14px 0 8px 18px;font-size:12px;text-transform:uppercase;
 letter-spacing:.06em;color:var(--text-muted)}
.plc-subregion>.card{margin-left:18px}
.roster th:nth-child(4),.roster td:nth-child(4){white-space:nowrap}
.fgrp{display:flex;flex-direction:column;gap:3px}
.fgrp label{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--text-muted)}
.fgrp select{min-width:160px;max-width:220px}
select[multiple]{padding:2px;vertical-align:top}
select[multiple] option{padding:3px 6px;border-radius:4px}
.toolbar button{font:inherit;background:var(--surface-2);color:var(--text-primary);
 border:1px solid var(--line);border-radius:8px;padding:6px 12px;cursor:pointer;align-self:flex-end}
.toolbar button:hover{background:var(--surface-3)}
.toolbar .chip{align-self:flex-end;margin-bottom:1px}
"""

EXTRA_JS = """
<script>
(function(){
  var LEVELS=['country','region','subregion','locality'];
  var sel={};
  LEVELS.forEach(function(lv){sel[lv]=document.getElementById('f'+lv.charAt(0).toUpperCase()+lv.slice(1));});

  var META=Array.prototype.map.call(document.querySelectorAll('.card'),function(card){
    return {
      anchor:card.id,
      country:card.getAttribute('data-country')||'',
      region:card.getAttribute('data-region')||'',
      subregion:card.getAttribute('data-subregion')||'',
      locality:card.getAttribute('data-locality')||'',
      name:card.getAttribute('data-name')||''
    };
  });

  function distinct(pool,key){
    var seen={},out=[];
    pool.forEach(function(m){var v=m[key];if(!(v in seen)){seen[v]=true;out.push(v);}});
    out.sort(function(a,b){
      if(a==='')return 1;
      if(b==='')return -1;
      return a.localeCompare(b);
    });
    return out;
  }

  function selectedSet(node){
    var s=new Set();
    Array.prototype.forEach.call(node.selectedOptions||[],function(o){s.add(o.value);});
    return s;
  }

  function fillOptions(node,values){
    var keep=selectedSet(node);
    node.innerHTML='';
    values.forEach(function(v){
      var o=document.createElement('option');
      o.value=v;
      o.textContent=v===''?'(Unspecified)':v;
      if(keep.has(v))o.selected=true;
      node.appendChild(o);
    });
  }

  function rebuildCascade(){
    var selC=selectedSet(sel.country);
    var poolR=META.filter(function(m){return !selC.size||selC.has(m.country);});
    fillOptions(sel.region,distinct(poolR,'region'));

    var selR=selectedSet(sel.region);
    var poolS=poolR.filter(function(m){return !selR.size||selR.has(m.region);});
    fillOptions(sel.subregion,distinct(poolS,'subregion'));

    var selS=selectedSet(sel.subregion);
    var poolL=poolS.filter(function(m){return !selS.size||selS.has(m.subregion);});
    fillOptions(sel.locality,distinct(poolL,'locality'));
  }

  window.filterPlaces=function(){
    rebuildCascade();
    var q=(document.getElementById('q').value||'').trim().toLowerCase();
    var selC=selectedSet(sel.country),selR=selectedSet(sel.region),
        selS=selectedSet(sel.subregion),selL=selectedSet(sel.locality);
    var shown=0;
    META.forEach(function(m){
      var show=true;
      if(q&&m.name.indexOf(q)===-1)show=false;
      if(show&&selC.size&&!selC.has(m.country))show=false;
      if(show&&selR.size&&!selR.has(m.region))show=false;
      if(show&&selS.size&&!selS.has(m.subregion))show=false;
      if(show&&selL.size&&!selL.has(m.locality))show=false;
      var el=document.getElementById(m.anchor);
      if(el)el.style.display=show?'':'none';
      if(show)shown++;
    });
    document.querySelectorAll('.place-country,.plc-region,.plc-subregion').forEach(function(g){
      var any=Array.prototype.some.call(g.querySelectorAll('.card'),function(c){
        return c.style.display!=='none';
      });
      g.style.display=any?'':'none';
    });
    var countEl=document.getElementById('fCount');
    if(countEl)countEl.textContent=shown+' of '+META.length+' places';
  };

  window.clearPlaceFilters=function(){
    document.getElementById('q').value='';
    LEVELS.forEach(function(lv){
      Array.prototype.forEach.call(sel[lv].options,function(o){o.selected=false;});
    });
    filterPlaces();
  };

  fillOptions(sel.country,distinct(META,'country'));
  filterPlaces();
})();
</script>
"""

CSV_COLUMNS = ["PlaceKey", "PlaceLabel", "Country", "CountryCode", "PersonName",
              "Relationship", "Line", "Generation", "Event", "Date", "Year",
              "Cemetery", "CemeteryAddress", "CemeteryPlot"]


def _to_int(v):
    try:
        if v in (None, ""):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _filter_rows(rows, max_gens, year_min, year_max, country):
    country_q = (country or "").strip().lower()
    want_all = country_q in ("", "all")
    out = []
    for r in rows:
        gen = _to_int(r.get("Generation"))
        if max_gens is not None and gen is not None and gen > max_gens:
            continue
        yr = _to_int(r.get("Year"))
        if yr is not None:
            if year_min is not None and yr < year_min:
                continue
            if year_max is not None and yr > year_max:
                continue
        if not want_all:
            c = (r.get("Country") or "").strip().lower()
            cc = (r.get("CountryCode") or "").strip().lower()
            if country_q not in (c, cc):
                continue
        out.append(r)
    return out


def _write_csv(path: Path, rows: list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csvmod.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({
                "PlaceKey": r.get("PlaceKey") or "", "PlaceLabel": r.get("PlaceLabel") or "",
                "Country": r.get("Country") or "", "CountryCode": r.get("CountryCode") or "",
                "PersonName": r.get("PersonName") or "", "Relationship": r.get("Relationship") or "",
                "Line": r.get("Line") or "", "Generation": r.get("Generation") if r.get("Generation") is not None else "",
                "Event": r.get("Event") or "", "Date": r.get("Date") or "", "Year": r.get("Year") or "",
                "Cemetery": r.get("Cemetery") or "", "CemeteryAddress": r.get("CemeteryAddress") or "",
                "CemeteryPlot": r.get("CemeteryPlot") or "",
            })
    return path


def _place_card(c: dict) -> str:
    anchor = c["anchor"]
    cem_html = ""
    if c["cemeteries"]:
        chunks = []
        for name, addr, plot in c["cemeteries"]:
            bits = [f'<span class="cem">{esc(name)}</span>']
            if addr:
                bits.append(esc(addr))
            if plot:
                bits.append(esc(plot))
            chunks.append(" &middot; ".join(bits))
        cem_html = f'<p class="who">{esc("Cemetery" if len(chunks) == 1 else "Cemeteries")}: {"; ".join(chunks)}</p>'

    rows_sorted = sorted(c["rows"], key=lambda r: (
        _to_int(r.get("Year")) if _to_int(r.get("Year")) is not None else 99999,
        r.get("PersonName") or ""))
    trs = []
    for r in rows_sorted:
        date_txt = esc(r.get("Date") or "") or '<span class="mut">undated</span>'
        rel = r.get("Relationship") or ""
        rel_txt = "Target person" if rel in ("self", "") else rel.capitalize()
        ev = r.get("Event") or "Event"
        trs.append(f'<tr><td>{esc(r.get("PersonName") or "")}</td><td>{esc(rel_txt)}</td>'
                   f'<td><span class="dot" style="background:{slot_var(ev)}"></span>{esc(ev)}</td>'
                   f'<td class="num">{date_txt}</td></tr>')
    table = ('<table><thead><tr><th>Person</th><th>Relationship</th><th>Event</th><th>Date</th></tr></thead>'
             f'<tbody>{"".join(trs)}</tbody></table>')

    return (f'<div class="card" id="{esc(anchor)}" data-name="{esc(c["label"].lower())}" '
           f'data-country="{esc(c["country"])}" data-region="{esc(c["region"])}" '
           f'data-subregion="{esc(c["subregion"])}" data-locality="{esc(c["locality"])}">'
           f'<h3>{esc(c["label"])}</h3>'
           f'<p class="who">{c["people"]} people &middot; {c["events"]} events &middot; {esc(c["span"])}</p>'
           f'{cem_html}{table}</div>')


def run(spec: RunSpec) -> list[Artifact]:
    rows = list(spec.pipeline.event_rows) if spec.pipeline else []

    max_gens = _to_int(spec.p("max_generations"))
    year_min = _to_int(spec.p("year_min"))
    year_max = _to_int(spec.p("year_max"))
    country_param = spec.p("country") or "All"

    filtered = _filter_rows(rows, max_gens, year_min, year_max, country_param)

    html_path = spec.out_dir / "locations.html"
    csv_path = spec.out_dir / "locations_roster.csv"
    title = f"Locations — {spec.target_name}"

    if not filtered:
        body = (f'<h1>Locations</h1>'
               f'<p class="sub">Every dated place for {esc(spec.target_name)} and ancestors, worldwide.</p>'
               f'<div class="note">No events match the current filters (generation / year range / country). '
               f'Try widening them.</div>')
        write_page(html_path, title, body, extra_css=EXTRA_CSS)
        _write_csv(csv_path, [])
        return [html_artifact(html_path, "Locations", note="No events matched the filters."),
               csv_artifact(csv_path, "Place roster (CSV)", note="Empty -- no events matched.")]

    places: dict[str, dict] = {}
    for r in filtered:
        key = r.get("PlaceKey") or f"??||||{r.get('PlaceRaw', '')}"
        p = places.setdefault(key, {
            "rows": [], "label": r.get("PlaceLabel") or r.get("PlaceRaw") or "Unknown place",
            "country": r.get("Country") or "Unknown", "countrycode": r.get("CountryCode") or "",
            "region": r.get("Region") or "", "subregion": r.get("Subregion") or "",
            "locality": r.get("Locality") or "",
        })
        p["rows"].append(r)

    cards = []
    for key, p in places.items():
        prows = p["rows"]
        people_ids = {r.get("PersonID") or r.get("PersonName") for r in prows}
        years = [y for y in (_to_int(r.get("Year")) for r in prows) if y is not None]
        span = f"{min(years)}–{max(years)}" if years else "undated"
        cem_seen, cems = set(), []
        for r in prows:
            if r.get("Cemetery"):
                tup = (r["Cemetery"], r.get("CemeteryAddress") or "", r.get("CemeteryPlot") or "")
                if tup not in cem_seen:
                    cem_seen.add(tup)
                    cems.append(tup)
        has_burial = any((r.get("Event") or "") == "Burial" for r in prows)
        cards.append({
            "key": key, "label": p["label"], "country": p["country"], "countrycode": p["countrycode"],
            "region": p["region"], "subregion": p["subregion"], "locality": p["locality"],
            "people": len(people_ids), "events": len(prows), "span": span,
            "cemeteries": cems, "has_burial": has_burial, "rows": prows,
        })

    # Best research stops first: burials, then people touched, then event volume.
    cards.sort(key=lambda c: (not c["has_burial"], -c["people"], -c["events"], c["label"] or ""))

    # place_anchor() sanitizes aggressively (spaces and hyphens both become "-"), so two
    # distinct PlaceKeys that differ only in punctuation -- "St-Constant" vs "St Constant" --
    # can collide. Anchors must be unique, since they are the map's deep-link contract, so
    # any collision after the first gets a numbered suffix.
    seen_anchors: dict[str, int] = {}
    for c in cards:
        base = place_anchor(c["key"])
        n = seen_anchors.get(base, 0)
        seen_anchors[base] = n + 1
        c["anchor"] = base if n == 0 else f"{base}-{n + 1}"

    # Publish the resolved PlaceKey -> anchor map. The map report deep-links into
    # these cards and cannot recompute the de-duplicated suffixes on its own, so
    # this file is the contract between the two reports rather than a guess.
    import json as _json
    (spec.out_dir / "place_anchors.json").write_text(
        _json.dumps({c["key"]: c["anchor"] for c in cards}, indent=1), encoding="utf-8")

    # Nested country -> state/province -> county tree, preserving the rank order the
    # cards are already sorted in (best research stops first) at every level. Region
    # and subregion are blank for the many places (most of the world, most towns) that
    # don't have that level -- those cards simply sit one level up with no sub-header.
    tree: dict[str, dict[str, dict[str, list]]] = {}
    for c in cards:
        tree.setdefault(c["country"], {}).setdefault(c["region"], {}).setdefault(c["subregion"], []).append(c)

    sections = []
    for country, regions in tree.items():
        country_cards = [c for subs in regions.values() for cs in subs.values() for c in cs]
        region_chunks = []
        for region, subregions in regions.items():
            region_cards = [c for cs in subregions.values() for c in cs]
            subregion_chunks = []
            for subregion, subcards in subregions.items():
                cards_html = "".join(_place_card(c) for c in subcards)
                if subregion:
                    # Connecticut's post-2022 "Xxx Planning Region" already names what
                    # it is; appending "County" to that would be wrong, so only add it
                    # to a bare county name.
                    self_describing = subregion.strip().lower().endswith("region")
                    label = (subregion if (self_describing or subcards[0]["countrycode"] != "US")
                            else f"{subregion} County")
                    subregion_chunks.append(
                        f'<div class="plc-subregion"><h4>{esc(label)} '
                        f'<span class="mut num">({len(subcards)})</span></h4>{cards_html}</div>')
                else:
                    subregion_chunks.append(f'<div class="plc-subregion">{cards_html}</div>')
            region_html = "".join(subregion_chunks)
            if region:
                region_chunks.append(
                    f'<div class="plc-region"><h3>{esc(region)} '
                    f'<span class="mut num">({len(region_cards)})</span></h3>{region_html}</div>')
            else:
                region_chunks.append(f'<div class="plc-region">{region_html}</div>')
        sections.append(f'<div class="place-country"><h2>{esc(country)} '
                        f'<span class="mut num">({len(country_cards)} place'
                        f'{"s" if len(country_cards) != 1 else ""})</span></h2>{"".join(region_chunks)}</div>')

    total_people = len({r.get("PersonID") or r.get("PersonName") for r in filtered})
    burial_places = sum(1 for c in cards if c["has_burial"])
    meta_chips = (f'<div class="meta"><span class="chip">{len(cards)} places</span>'
                 f'<span class="chip">{len(tree)} countries</span>'
                 f'<span class="chip">{total_people} people</span>'
                 f'<span class="chip">{len(filtered)} events</span>'
                 f'<span class="chip">{burial_places} with burials</span></div>')

    toolbar = ('<div class="toolbar">'
              '<input type="search" id="q" placeholder="Filter by place…" oninput="filterPlaces()">'
              '<div class="fgrp"><label for="fCountry">Country</label>'
              '<select id="fCountry" multiple size="6" onchange="filterPlaces()"></select></div>'
              '<div class="fgrp"><label for="fRegion">State / province</label>'
              '<select id="fRegion" multiple size="6" onchange="filterPlaces()"></select></div>'
              '<div class="fgrp"><label for="fSubregion">County</label>'
              '<select id="fSubregion" multiple size="6" onchange="filterPlaces()"></select></div>'
              '<div class="fgrp"><label for="fLocality">City / town</label>'
              '<select id="fLocality" multiple size="6" onchange="filterPlaces()"></select></div>'
              '<button type="button" onclick="clearPlaceFilters()">Clear filters</button>'
              '<span class="chip"><span id="fCount"></span></span>'
              '</div>')

    body = (f'<h1>Locations</h1>'
           f'<p class="sub">Every dated place for {esc(spec.target_name)} and ancestors, grouped by country, '
           f'state/province and county, and ranked to put the best research stops -- burial grounds, then '
           f'places that touch the most people -- first. Hold Ctrl/Cmd (or Shift for a range) to select more '
           f'than one value in a filter.</p>'
           f'{meta_chips}{toolbar}{"".join(sections)}{EXTRA_JS}')

    write_page(html_path, title, body, extra_css=EXTRA_CSS)
    _write_csv(csv_path, filtered)

    return [html_artifact(html_path, "Locations",
                          note=f"{len(cards)} places across {len(tree)} countries"),
           csv_artifact(csv_path, "Place roster (CSV)", note=f"{len(filtered)} event rows")]


REPORT = Report(
    id="locations",
    title="Locations",
    description=("Every dated event organised by place instead of by person -- one card per distinct place, "
                "worldwide, with cemetery detail and a roster of who was there and when. Ranked so the best "
                "research stops come first."),
    run=run,
    params=[P_MAX_GENS, P_YEAR_MIN, P_YEAR_MAX, P_COUNTRY],
    needs_events=True,
    needs_target=True,
    group="Research",
    order=21,
)
