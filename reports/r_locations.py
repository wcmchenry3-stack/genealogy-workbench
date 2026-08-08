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
.roster th:nth-child(4),.roster td:nth-child(4){white-space:nowrap}
"""

EXTRA_JS = """
<script>
function filterPlaces(){
  var q=(document.getElementById('q').value||'').trim().toLowerCase();
  document.querySelectorAll('.place-country').forEach(function(section){
    var any=false;
    section.querySelectorAll('.card').forEach(function(card){
      var name=card.getAttribute('data-name')||'';
      var show=!q||name.indexOf(q)>-1;
      card.style.display=show?'':'none';
      if(show)any=true;
    });
    section.style.display=any?'':'none';
  });
}
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

    return (f'<div class="card" id="{esc(anchor)}" data-name="{esc(c["label"].lower())}">'
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

    order_seen, groups = [], {}
    for c in cards:
        groups.setdefault(c["country"], []).append(c)
        if c["country"] not in order_seen:
            order_seen.append(c["country"])

    sections = []
    for country in order_seen:
        group_cards = groups[country]
        cards_html = "".join(_place_card(c) for c in group_cards)
        sections.append(f'<div class="place-country"><h2>{esc(country)} '
                        f'<span class="mut num">({len(group_cards)} place'
                        f'{"s" if len(group_cards) != 1 else ""})</span></h2>{cards_html}</div>')

    total_people = len({r.get("PersonID") or r.get("PersonName") for r in filtered})
    burial_places = sum(1 for c in cards if c["has_burial"])
    meta_chips = (f'<div class="meta"><span class="chip">{len(cards)} places</span>'
                 f'<span class="chip">{len(order_seen)} countries</span>'
                 f'<span class="chip">{total_people} people</span>'
                 f'<span class="chip">{len(filtered)} events</span>'
                 f'<span class="chip">{burial_places} with burials</span></div>')

    toolbar = ('<div class="toolbar">'
              '<input type="search" id="q" placeholder="Filter by place…" oninput="filterPlaces()">'
              '</div>')

    body = (f'<h1>Locations</h1>'
           f'<p class="sub">Every dated place for {esc(spec.target_name)} and ancestors, grouped by country '
           f'and ranked to put the best research stops -- burial grounds, then places that touch the most '
           f'people -- first.</p>'
           f'{meta_chips}{toolbar}{"".join(sections)}{EXTRA_JS}')

    write_page(html_path, title, body, extra_css=EXTRA_CSS)
    _write_csv(csv_path, filtered)

    return [html_artifact(html_path, "Locations",
                          note=f"{len(cards)} places across {len(order_seen)} countries"),
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
