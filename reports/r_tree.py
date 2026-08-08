#!/usr/bin/env python3
"""
reports/r_tree.py
--------------------
Registry adapter for gedcom_visualizer.create_visual_tree.

Draws a printable ancestor chart: four generations of boxes per page, with
"To page N" links where a branch continues onto another page so you can flip
through a large tree on paper without losing your place.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPORTS_DIR = Path(__file__).resolve().parent
_CORE_DIR = _REPORTS_DIR.parent / "core"
for _p in (_REPORTS_DIR, _CORE_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from base import Report, RunSpec, Artifact, P_MAX_GENS  # noqa: E402
from theme import write_page, esc  # noqa: E402
from gedcom_visualizer import create_visual_tree  # noqa: E402


def _pdf_page_count(pdf_path: Path) -> int | None:
    """Best-effort, cheap page count -- never worth failing the report over."""
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pdf_path)).pages)
    except Exception:
        pass
    try:
        data = pdf_path.read_bytes()
        pages = re.findall(rb"/Type\s*/Page(?!s)", data)
        return len(pages) or None
    except Exception:
        return None


def run(spec: RunSpec) -> list[Artifact]:
    master_csv = spec.data_dir / "master_tree.csv"
    out_pdf = spec.out_dir / "ancestor_chart.pdf"
    out_html = spec.out_dir / "ancestor_chart.html"

    max_gens = int(spec.p("max_generations", 999) or 999)

    spec.log(f"Drawing ancestor chart for {spec.target_name} ({max_gens} generations)...")
    create_visual_tree(str(master_csv), str(out_pdf), spec.target_id, max_gens)

    page_count = _pdf_page_count(out_pdf)
    size_kb = out_pdf.stat().st_size / 1024 if out_pdf.exists() else 0
    spec.log(f"Ancestor chart: {page_count or '?'} pages, {size_kb:.0f} KB.")

    page_note = f"{page_count} page{'s' if page_count != 1 else ''}" if page_count else "PDF"
    body = (
        f"<h1>Ancestor Chart</h1>"
        f'<p class="sub">A printable, four-generations-per-page ancestor chart for '
        f"{esc(spec.target_name)}, with page links where a branch continues.</p>"
        f'<div class="meta">'
        f'<span class="chip">Focus: {esc(spec.target_name)}</span>'
        f'<span class="chip">Max generations: {max_gens}</span>'
        f'<span class="chip">{esc(page_note)}</span>'
        f'<span class="chip">{size_kb:.0f} KB</span>'
        f"</div>"
        f'<div class="card"><h3>ancestor_chart.pdf</h3>'
        f'<p class="who">Open the PDF download to view or print the chart.</p>'
        f'<p><a href="ancestor_chart.pdf">Open ancestor_chart.pdf</a></p></div>'
    )
    write_page(out_html, "Ancestor Chart", body)

    return [
        Artifact(path=out_pdf, title="Ancestor Chart (PDF)", kind="pdf", primary=True, note=page_note),
        Artifact(path=out_html, title="Ancestor Chart", kind="html", primary=False,
                 note="Landing page"),
    ]


REPORT = Report(
    id="tree",
    title="Ancestor Chart",
    description=("A printable ancestor chart, four generations per page, with page-to-page "
                "links where a branch runs deeper than fits -- the classic pedigree chart "
                "you'd print out or hand to a relative."),
    run=run,
    params=[P_MAX_GENS],
    needs_master_csv=True,
    needs_target=True,
    group="Reports",
    order=10,
)
