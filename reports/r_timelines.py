#!/usr/bin/env python3
"""
reports/r_timelines.py
-----------------------
Per-ancestor chronological timelines, worldwide.

One card per person: name, relationship to the target, generation, line, an
SVG strip of their dated events, and a table of every dated place they
touched. Every strip in the report shares one year scale -- derived from the
filtered data, never hardcoded -- so a birth in 1690 Staffordshire and a birth
in 1890 Michigan land at comparable positions and generations read as what
they are: comparable widths of time.

Undated events cannot be placed on a strip (there is no x for them), but they
are real research leads, so they still appear in the person's table. The
report says so once, rather than silently dropping them.
"""
from __future__ import annotations

from pathlib import Path

from .base import Artifact, Report, RunSpec, P_MAX_GENS, P_YEAR_MAX, P_YEAR_MIN, html_artifact
from .theme import EVENT_ORDER, esc, legend, slot_var, write_page

EXTRA_CSS = """
.strip{margin:10px 0 14px}
.person{scroll-margin-top:20px}
.gen-block h2{margin-top:40px}
"""

EXTRA_JS = """
<script>
// Cached once at load instead of re-querying the DOM on every keystroke --
// with thousands of .person cards, a fresh querySelectorAll('.gen-block')
// + nested querySelectorAll('.person') on every oninput event is the
// difference between typing feeling instant and feeling laggy.
var TL_INDEX=null;
function tlIndex(){
  if(!TL_INDEX){
    TL_INDEX=Array.prototype.map.call(document.querySelectorAll('.gen-block'),function(block){
      return {block:block, cards:Array.prototype.map.call(block.querySelectorAll('.person'),function(card){
        return {el:card, name:card.getAttribute('data-name')||'', line:card.getAttribute('data-line')||''};
      })};
    });
  }
  return TL_INDEX;
}
function filterTimelines(){
  var q=(document.getElementById('q').value||'').trim().toLowerCase();
  var line=document.getElementById('lineSel').value;
  tlIndex().forEach(function(g){
    var any=false;
    g.cards.forEach(function(c){
      var show=(!q||c.name.indexOf(q)>-1)&&(!line||c.line===line);
      c.el.style.display=show?'':'none';
      if(show)any=true;
    });
    g.block.style.display=any?'':'none';
  });
}
var _tlDebounce=null;
function filterTimelinesDebounced(){
  clearTimeout(_tlDebounce);
  _tlDebounce=setTimeout(filterTimelines,120);
}
</script>
"""


def _to_int(v):
    try:
        if v in (None, ""):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _filter_rows(rows, max_gens, year_min, year_max):
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
        out.append(r)
    return out


def _nice_step(span: int) -> int:
    """A tick interval that yields roughly 6-9 ticks across `span` years."""
    if span <= 0:
        return 1
    raw = span / 7
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000):
        if step >= raw:
            return step
    return 2000


def _timeline_svg(events: list, ymin: int, ymax: int, width: int = 860, height: int = 62) -> str:
    """One shared-scale SVG strip. `events` are dicts with an int Year."""
    pad = 16
    axis_y = height - 22

    def x_of(y):
        if ymax == ymin:
            return width / 2
        return pad + (y - ymin) / (ymax - ymin) * (width - 2 * pad)

    parts = [f'<svg class="strip" viewBox="0 0 {width} {height}" width="100%" height="{height}" '
             f'role="img" aria-label="Timeline strip">']
    parts.append(f'<line x1="{pad}" y1="{axis_y}" x2="{width - pad}" y2="{axis_y}" '
                 f'style="stroke:var(--line)" stroke-width="1"/>')

    if ymax == ymin:
        parts.append(f'<text x="{x_of(ymin):.1f}" y="{height - 6}" font-size="9" text-anchor="middle" '
                     f'style="fill:var(--text-muted)">{ymin}</text>')
    else:
        step = _nice_step(ymax - ymin)
        y = (ymin // step) * step
        while y <= ymax:
            if y >= ymin:
                x = x_of(y)
                parts.append(f'<line x1="{x:.1f}" y1="{axis_y - 3}" x2="{x:.1f}" y2="{axis_y + 3}" '
                             f'style="stroke:var(--text-muted)" stroke-width="1"/>')
                parts.append(f'<text x="{x:.1f}" y="{height - 6}" font-size="9" text-anchor="middle" '
                             f'style="fill:var(--text-muted)">{y}</text>')
            y += step

    for e in events:
        x = x_of(e["Year"])
        color = slot_var(e["Event"])
        label = esc(f'{e["Event"]}, {e["Date"] or e["Year"]}')
        parts.append(f'<circle cx="{x:.1f}" cy="{axis_y}" r="4.5" style="fill:{color}" '
                     f'stroke="var(--surface-1)" stroke-width="1.5"><title>{label}</title></circle>')
    parts.append("</svg>")
    return "".join(parts)


def _detail_html(r: dict) -> str:
    bits = []
    if r.get("Event") == "Burial":
        if r.get("Cemetery"):
            bits.append(f'<span class="cem">{esc(r["Cemetery"])}</span>')
        if r.get("CemeteryAddress"):
            bits.append(esc(r["CemeteryAddress"]))
        if r.get("CemeteryPlot"):
            bits.append(esc(r["CemeteryPlot"]))
    raw, label = r.get("PlaceRaw") or "", r.get("PlaceLabel") or ""
    if raw and raw != label:
        bits.append(f'<span class="mut">{esc(raw)}</span>')
    return " &middot; ".join(bits)


def _person_block(meta: dict, rows: list, ymin: int, ymax: int, has_scale: bool) -> str:
    name = meta.get("PersonName") or "(unknown)"
    rel = meta.get("Relationship") or ""
    line = meta.get("Line") or ""
    dated = [r for r in rows if _to_int(r.get("Year")) is not None]

    if has_scale and dated:
        svg = _timeline_svg(
            [{"Year": _to_int(r["Year"]), "Event": r.get("Event") or "Event", "Date": r.get("Date")} for r in dated],
            ymin, ymax)
    else:
        svg = '<p class="mut">No dated events to plot for this person.</p>'

    trs = []
    for r in rows:
        date_txt = esc(r.get("Date") or "") or '<span class="mut">undated</span>'
        qual = r.get("DateQualifier")
        if qual:
            date_txt = f'{date_txt} <span class="mut">({esc(qual)})</span>'
        ev = r.get("Event") or "Event"
        place = esc(r.get("PlaceLabel") or r.get("PlaceRaw") or "")
        trs.append(
            f'<tr><td class="num">{date_txt}</td>'
            f'<td><span class="dot" style="background:{slot_var(ev)}"></span>{esc(ev)}</td>'
            f'<td>{place}</td><td>{_detail_html(r)}</td></tr>')

    table = ('<table><thead><tr><th>Date</th><th>Event</th><th>Place</th><th>Detail</th></tr></thead>'
             f'<tbody>{"".join(trs)}</tbody></table>')

    rel_txt = "Target person" if rel in ("self", "") else rel.capitalize()
    line_txt = "" if line in ("self", "") else f' &middot; {esc(line)} line'

    return (f'<div class="card person" data-name="{esc(name.lower())}" data-line="{esc(line)}">'
           f'<h3>{esc(name)}</h3><p class="who">{esc(rel_txt)}{line_txt}</p>{svg}{table}</div>')


def run(spec: RunSpec) -> list[Artifact]:
    rows = list(spec.pipeline.event_rows) if spec.pipeline else []

    max_gens = _to_int(spec.p("max_generations"))
    year_min = _to_int(spec.p("year_min"))
    year_max = _to_int(spec.p("year_max"))

    filtered = _filter_rows(rows, max_gens, year_min, year_max)
    out_path = spec.out_dir / "timelines.html"
    title = f"Ancestor Timelines — {spec.target_name}"

    if not filtered:
        body = (f'<h1>Ancestor Timelines</h1>'
               f'<p class="sub">Chronological life events for {esc(spec.target_name)} and ancestors.</p>'
               f'<div class="note">No events match the current filters (generation / year range). '
               f'Try widening them.</div>')
        write_page(out_path, title, body, extra_css=EXTRA_CSS)
        return [html_artifact(out_path, "Ancestor Timelines", note="No events matched the filters.")]

    people: dict[str, dict] = {}
    for r in filtered:
        pid = r.get("PersonID") or r.get("PersonName")
        entry = people.setdefault(pid, {"meta": r, "rows": []})
        entry["rows"].append(r)

    dated_years = [y for y in (_to_int(r.get("Year")) for r in filtered) if y is not None]
    has_scale = bool(dated_years)
    ymin = min(dated_years) if has_scale else 0
    ymax = max(dated_years) if has_scale else 0
    undated_count = len(filtered) - len(dated_years)

    by_gen: dict[int, list] = {}
    for pid, entry in people.items():
        gen = _to_int(entry["meta"].get("Generation")) or 0
        by_gen.setdefault(gen, []).append((pid, entry))

    gen_blocks = []
    for gen in sorted(by_gen):
        entries = sorted(by_gen[gen], key=lambda t: (t[1]["meta"].get("PersonName") or ""))
        cards = "".join(_person_block(e["meta"], e["rows"], ymin, ymax, has_scale) for _pid, e in entries)
        label = "Self" if gen == 0 else f"Generation {gen}"
        gen_blocks.append(f'<div class="gen-block" data-gen="{gen}">'
                          f'<h2>{esc(label)} <span class="mut num">({len(entries)})</span></h2>{cards}</div>')

    used_types = [t for t in EVENT_ORDER if any((r.get("Event") or "") == t for r in filtered)]
    year_chip = f"{ymin}–{ymax}" if has_scale else "no dated events"

    meta_chips = (f'<div class="meta"><span class="chip">{len(people)} people</span>'
                 f'<span class="chip">{len(filtered)} events</span>'
                 f'<span class="chip">{esc(year_chip)}</span></div>')

    undated_note = ""
    if undated_count:
        undated_note = (f'<div class="note">{undated_count} event(s) have no year and are listed in each '
                        f'person’s table but cannot be plotted on the timeline strip.</div>')

    toolbar = ('<div class="toolbar">'
              '<input type="search" id="q" placeholder="Filter by name…" oninput="filterTimelinesDebounced()">'
              '<select id="lineSel" onchange="filterTimelines()">'
              '<option value="">All lines</option>'
              '<option value="paternal">Paternal</option>'
              '<option value="maternal">Maternal</option>'
              '<option value="self">Self</option>'
              '</select></div>')

    body = (f'<h1>Ancestor Timelines</h1>'
           f'<p class="sub">Chronological life events for {esc(spec.target_name)} and ancestors, '
           f'one strip per person, all sharing a single year scale so generations are comparable.</p>'
           f'{meta_chips}{legend(used_types)}{toolbar}{undated_note}{"".join(gen_blocks)}{EXTRA_JS}')

    write_page(out_path, title, body, extra_css=EXTRA_CSS)
    return [html_artifact(out_path, "Ancestor Timelines",
                          note=f"{len(people)} people, {len(filtered)} events, {year_chip}")]


REPORT = Report(
    id="timelines",
    title="Ancestor Timelines",
    description=("A chronological strip and event table for every ancestor, generation by generation, "
                "worldwide -- one shared year scale so lifespans across continents and centuries are "
                "visually comparable."),
    run=run,
    params=[P_MAX_GENS, P_YEAR_MIN, P_YEAR_MAX],
    needs_events=True,
    needs_target=True,
    group="Research",
    order=20,
)
