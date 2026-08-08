#!/usr/bin/env python3
"""
reports/r_immigrants.py
-------------------------
Registry adapter for gedcom_immigrant_report.generate_immigrant_exit_report.

Walks every ancestral branch back from the focus person and finds, on each
branch, the first ancestor who was born outside the United States -- the
point where that line of the family "exits" the US and the immigrant
generation to look at first. Branches that run out of records, loop, or
never leave the US are reported too, so you can see how far each line has
been traced.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPORTS_DIR = Path(__file__).resolve().parent
_CORE_DIR = _REPORTS_DIR.parent / "core"
for _p in (_REPORTS_DIR, _CORE_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from base import Report, RunSpec, Artifact, csv_artifact, html_artifact, P_MAX_GENS  # noqa: E402
from tabular import write_csv_report_page  # noqa: E402
from gedcom_immigrant_report import generate_immigrant_exit_report  # noqa: E402


def run(spec: RunSpec) -> list[Artifact]:
    master_csv = spec.data_dir / "master_tree.csv"
    out_csv = spec.out_dir / "immigrants.csv"
    out_html = spec.out_dir / "immigrants.html"

    max_gens = int(spec.p("max_generations", 12) or 12)

    spec.log(f"Tracing immigrant branches for {spec.target_name} ({max_gens} generations)...")
    generate_immigrant_exit_report(
        master_csv=str(master_csv), out_csv=str(out_csv),
        root_id=spec.target_id, max_gens=max_gens,
    )

    _, row_count = write_csv_report_page(
        out_csv, out_html,
        title="Immigrant Ancestors",
        description=(f"For every ancestral branch of {spec.target_name}, the first ancestor born "
                     f"outside the United States -- the immigrant generation for that line -- "
                     f"or, if none is found, where and why the branch stops."),
        chips=[f"Focus: {spec.target_name}", f"Max generations: {max_gens}"],
        empty_message="No ancestor branches were found for this person.",
    )
    spec.log(f"Immigrant report: {row_count} branches written.")

    return [
        html_artifact(out_html, "Immigrant Ancestors", note=f"{row_count} branches", primary=True),
        csv_artifact(out_csv, "Immigrant Ancestors (CSV)", note=f"{row_count} rows"),
    ]


REPORT = Report(
    id="immigrants",
    title="Immigrant Ancestors",
    description=("For every branch of the family tree, finds the first ancestor born outside "
                "the United States -- the immigrant who started that line's American story -- "
                "so you can see when and where each branch of the family arrived."),
    run=run,
    params=[P_MAX_GENS],
    needs_master_csv=True,
    needs_target=True,
    group="Reports",
    order=40,
)
