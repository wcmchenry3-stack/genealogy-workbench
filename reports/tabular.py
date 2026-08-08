#!/usr/bin/env python3
"""
reports/tabular.py
-------------------
One CSV -> HTML table renderer, shared by every report whose underlying
logic only knows how to write a CSV.

Several reports in this app were ported from standalone scripts whose only
output is a CSV file. Handing a user a bare CSV next to reports that render
as polished HTML pages would make the product feel like two different tools
stapled together. So every CSV-producing report also builds an HTML view
through this module: same sticky, click-to-sort header, same client-side
filter box, same numeric-column alignment, same look, every time. The CSV
itself is still produced by the original, untouched report logic and is
always attached as the secondary download.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional, Sequence

from theme import esc, write_page

TABLE_CSS = """
.tbl-wrap{border:1px solid var(--line);border-radius:12px;overflow:auto;max-height:72vh}
table.tbl{width:100%}
table.tbl thead th{position:sticky;top:0;background:var(--surface-1);cursor:pointer;
 user-select:none;white-space:nowrap}
table.tbl thead th:hover{color:var(--text-primary)}
table.tbl thead th .arrow{opacity:.35;margin-left:5px;font-size:10px}
table.tbl thead th[aria-sort]{color:var(--text-primary)}
table.tbl thead th[aria-sort] .arrow{opacity:1}
table.tbl tbody tr.tbl-hidden{display:none}
.badge{display:inline-flex;align-items:center;gap:6px;font-weight:600;font-size:12.5px;
 white-space:nowrap}
.badge .dot{width:8px;height:8px;border-radius:50%;display:inline-block;flex:none}
"""

TABLE_JS = """
<script>
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[data-tbl]').forEach(function (root) {
    var table = root.querySelector('table.tbl');
    if (!table) return;
    var tbody = table.tBodies[0];
    var rows = Array.prototype.slice.call(tbody.rows);
    var total = rows.length;
    var search = root.querySelector('input[data-tbl-filter]');
    var countEl = root.querySelector('[data-tbl-count]');

    function updateCount() {
      if (!countEl) return;
      var visible = rows.filter(function (r) { return !r.classList.contains('tbl-hidden'); }).length;
      countEl.textContent = (visible === total)
        ? (total + ' row' + (total === 1 ? '' : 's'))
        : (visible + ' of ' + total + ' rows');
    }

    if (search) {
      search.addEventListener('input', function () {
        var q = search.value.trim().toLowerCase();
        rows.forEach(function (r) {
          var hit = !q || r.textContent.toLowerCase().indexOf(q) !== -1;
          r.classList.toggle('tbl-hidden', !hit);
        });
        updateCount();
      });
    }

    table.querySelectorAll('thead th').forEach(function (th, idx) {
      th.addEventListener('click', function () {
        var dir = th.getAttribute('aria-sort') === 'ascending' ? 'descending' : 'ascending';
        table.querySelectorAll('thead th').forEach(function (h) { h.removeAttribute('aria-sort'); });
        th.setAttribute('aria-sort', dir);
        var mult = dir === 'ascending' ? 1 : -1;

        var sorted = rows.slice().sort(function (a, b) {
          var av = a.cells[idx].getAttribute('data-sort');
          var bv = b.cells[idx].getAttribute('data-sort');
          if (av === null) av = a.cells[idx].textContent.trim();
          if (bv === null) bv = b.cells[idx].textContent.trim();
          var an = parseFloat(av), bn = parseFloat(bv);
          var bothNum = av !== '' && bv !== '' && !isNaN(an) && !isNaN(bn);
          if (bothNum) return (an - bn) * mult;
          return av.localeCompare(bv) * mult;
        });
        sorted.forEach(function (r) { tbody.appendChild(r); });
        rows = sorted;
      });
    });

    updateCount();
  });
});
</script>
"""

# Result-style values coloured consistently wherever a report emits them.
# Colour is never the only signal: the text label is always rendered too.
_RESULT_ROLE = {
    "PASS": "--s5",
    "FAIL": "--s1",
    "WARN": "--s3",
    "SKIP": "--text-muted",
}


def _is_numeric(value: str) -> bool:
    v = (value or "").strip()
    if not v:
        return False
    try:
        float(v.replace(",", ""))
        return True
    except ValueError:
        return False


def read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict]]:
    """Read a CSV back as (fieldnames, rows). Read-only; never touches the source."""
    csv_path = Path(csv_path)
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(r) for r in reader]
    return fieldnames, rows


def badge_html(value: str) -> str:
    """A coloured dot + the value's own text -- colour is decoration, not the message."""
    role = _RESULT_ROLE.get((value or "").strip().upper())
    if not role:
        return esc(value)
    return (f'<span class="badge"><span class="dot" style="background:var({role})"></span>'
            f'{esc(value)}</span>')


def render_table(fieldnames: Sequence[str], rows: Sequence[dict], *,
                 table_id: str = "tbl", badge_column: Optional[str] = None,
                 filter_placeholder: str = "Filter rows…") -> str:
    """Build the toolbar + sortable/filterable table markup for one CSV's rows."""
    if not fieldnames or not rows:
        return '<p class="sub">No rows to show.</p>'

    numeric_cols = set()
    for col in fieldnames:
        sample = [r.get(col, "") for r in rows if (r.get(col, "") or "").strip()][:100]
        if sample and all(_is_numeric(v) for v in sample):
            numeric_cols.add(col)

    thead = "".join(f"<th>{esc(col)}<span class=\"arrow\">▴▾</span></th>" for col in fieldnames)

    body_rows = []
    for r in rows:
        cells = []
        for col in fieldnames:
            raw = r.get(col, "") or ""
            cls = ' class="num"' if col in numeric_cols else ""
            if badge_column and col == badge_column:
                cells.append(f'<td{cls} data-sort="{esc(raw)}">{badge_html(raw)}</td>')
            else:
                cells.append(f"<td{cls}>{esc(raw)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    count_label = f'{len(rows)} row{"" if len(rows) == 1 else "s"}'
    return (
        f'<div data-tbl id="{esc(table_id)}">'
        f'<div class="toolbar">'
        f'<input type="search" data-tbl-filter placeholder="{esc(filter_placeholder)}" '
        f'aria-label="Filter rows">'
        f'<span class="chip"><span data-tbl-count>{count_label}</span></span>'
        f"</div>"
        f'<div class="tbl-wrap"><table class="tbl"><thead><tr>{thead}</tr></thead>'
        f"<tbody>{''.join(body_rows)}</tbody></table></div>"
        f"</div>"
    )


def write_csv_report_page(csv_path: Path, out_html_path: Path, *, title: str, description: str,
                          chips: Optional[list[str]] = None, badge_column: Optional[str] = None,
                          empty_message: str = "No rows were produced for this run.",
                          extra_body: str = "") -> tuple[Path, int]:
    """
    Read a CSV a report already wrote and render the matching styled HTML page.
    Returns (html_path, row_count) so the caller can build its count chip / note.
    """
    fieldnames, rows = read_csv_rows(csv_path)
    chip_html = "".join(f'<span class="chip">{esc(c)}</span>' for c in (chips or []))
    table_html = (render_table(fieldnames, rows, badge_column=badge_column)
                  if rows else f'<p class="sub">{esc(empty_message)}</p>')

    body = (
        f"<h1>{esc(title)}</h1>"
        f'<p class="sub">{esc(description)}</p>'
        f'<div class="meta">{chip_html}</div>'
        f"{extra_body}"
        f"{table_html}"
    )
    write_page(out_html_path, title, body, extra_css=TABLE_CSS, extra_head=TABLE_JS)
    return Path(out_html_path), len(rows)
