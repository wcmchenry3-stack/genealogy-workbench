#!/usr/bin/env python3
"""
reports/r_diagnostics.py
-------------------------
Registry adapter for gedcom_analyzer.run_diagnostics.

Runs a set of sanity checks against the parent/child links in the tree --
parents too young, a parent who died before the child was born, a birthplace
implausibly far from a parent's -- and flags each as PASS/FAIL/WARN/SKIP so
you can spot likely data-entry mistakes or mis-linked relatives without
combing the raw data by hand.
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
from gedcom_analyzer import run_diagnostics  # noqa: E402


def run(spec: RunSpec) -> list[Artifact]:
    master_csv = spec.data_dir / "master_tree.csv"
    out_csv = spec.out_dir / "diagnostics.csv"
    out_html = spec.out_dir / "diagnostics.html"

    max_gens = int(spec.p("max_generations", 999) or 999)

    spec.log(f"Running relationship diagnostics for {spec.target_name} ({max_gens} generations)...")
    run_diagnostics(str(master_csv), str(out_csv), spec.target_id, max_gens)

    _, row_count = write_csv_report_page(
        out_csv, out_html,
        title="Relationship Diagnostics",
        description=(f"Automated sanity checks on every parent/child link found while tracing "
                     f"{spec.target_name}'s ancestry -- ages, lifespans, and birth/death "
                     f"locations that don't add up are flagged for review."),
        chips=[f"Focus: {spec.target_name}", f"Max generations: {max_gens}"],
        badge_column="Result",
        empty_message="No ancestor relationships were found to check.",
    )
    spec.log(f"Diagnostics: {row_count} checks written.")

    return [
        html_artifact(out_html, "Relationship Diagnostics", note=f"{row_count} checks", primary=True),
        csv_artifact(out_csv, "Diagnostics (CSV)", note=f"{row_count} rows"),
    ]


REPORT = Report(
    id="diagnostics",
    title="Relationship Diagnostics",
    description=("Flags parent/child relationships in the tree that look implausible -- a parent "
                "too young, a parent who died before the child's birth, or a birthplace far from "
                "a parent's -- so you can catch likely data-entry errors or wrong links."),
    run=run,
    params=[P_MAX_GENS],
    needs_master_csv=True,
    needs_target=True,
    group="Quality",
    order=20,
)
