#!/usr/bin/env python3
"""
reports/r_spouses.py
----------------------
Registry adapter for gedcom_spouse_relationships_report.generate_spouse_relationships_report.

Infers every couple in the tree (from shared children) and checks whether
the two people are also blood relatives of each other -- siblings, cousins,
or more distant kin -- which is common in older or rural family trees. This
is a whole-tree scan; it has no single focus person.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPORTS_DIR = Path(__file__).resolve().parent
_CORE_DIR = _REPORTS_DIR.parent / "core"
for _p in (_REPORTS_DIR, _CORE_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from base import Report, Param, RunSpec, Artifact, csv_artifact, html_artifact  # noqa: E402
from tabular import write_csv_report_page  # noqa: E402
from gedcom_spouse_relationships_report import generate_spouse_relationships_report  # noqa: E402


def run(spec: RunSpec) -> list[Artifact]:
    master_csv = spec.data_dir / "master_tree.csv"
    out_csv = spec.out_dir / "spouse_relationships.csv"
    out_html = spec.out_dir / "spouse_relationships.html"

    max_depth = int(spec.p("max_depth", 12) or 12)

    spec.log(f"Checking couples for blood relationships (max depth={max_depth})...")
    generate_spouse_relationships_report(
        master_csv=str(master_csv), out_csv=str(out_csv), max_depth=max_depth,
    )

    _, row_count = write_csv_report_page(
        out_csv, out_html,
        title="Spouse Relationships",
        description=("Every couple inferred from shared children, checked for a common ancestor "
                     "on both sides -- siblings, cousins, and more distant blood relationships "
                     "between spouses are flagged with their closest shared ancestor."),
        chips=[f"Max depth: {max_depth}"],
        badge_column=None,
        empty_message="No couples with shared children were found in the tree.",
    )
    spec.log(f"Spouse relationships: {row_count} couples written.")

    return [
        html_artifact(out_html, "Spouse Relationships", note=f"{row_count} couples", primary=True),
        csv_artifact(out_csv, "Spouse Relationships (CSV)", note=f"{row_count} rows"),
    ]


REPORT = Report(
    id="spouses",
    title="Spouse Relationships",
    description=("Checks every inferred couple in the tree for a shared blood ancestor -- "
                "siblings, cousins, and other relatives who married each other -- which is "
                "common in older family trees and easy to miss by eye."),
    run=run,
    params=[
        Param("max_depth", "Max depth", "int", 12,
             "How many generations back to search for a common ancestor between each couple.",
             min=1, max=30),
    ],
    needs_master_csv=True,
    needs_target=False,
    group="Reports",
    order=50,
)
