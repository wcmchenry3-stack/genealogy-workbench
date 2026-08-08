#!/usr/bin/env python3
"""
reports/r_duplicates.py
-------------------------
Registry adapter for gedcom_duplicates.run_duplicate_detection.

Scans every person in the tree for likely duplicate entries -- the same
individual recorded twice under slightly different names, dates or
spellings -- and scores each candidate pair so you know which ones are worth
merging first. This is a whole-tree scan; it has no single focus person.
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
from gedcom_duplicates import run_duplicate_detection  # noqa: E402


def run(spec: RunSpec) -> list[Artifact]:
    master_csv = spec.data_dir / "master_tree.csv"
    out_csv = spec.out_dir / "duplicates.csv"
    out_html = spec.out_dir / "duplicates.html"

    score_threshold = int(spec.p("score_threshold", 70))
    birth_window_years = int(spec.p("birth_window_years", 5))

    spec.log(f"Scanning for probable duplicates (threshold={score_threshold}, "
             f"birth window={birth_window_years}y)...")
    run_duplicate_detection(
        str(master_csv), str(out_csv),
        score_threshold=score_threshold,
        birth_window_years=birth_window_years,
        gedcom_path_for_spouses=str(spec.gedcom_path) if spec.gedcom_path else None,
    )

    _, row_count = write_csv_report_page(
        out_csv, out_html,
        title="Possible Duplicate People",
        description=("Every pair of people whose names, dates, places, parents, children or "
                     "spouses look similar enough to be the same individual recorded twice, "
                     "ranked by how strong the match is -- highest scores are the best "
                     "candidates to review and merge first."),
        chips=[f"Score threshold: {score_threshold}", f"Birth window: {birth_window_years}y"],
        badge_column=None,
        empty_message="No candidate duplicate pairs met the score threshold.",
    )
    spec.log(f"Duplicates: {row_count} candidate pairs written.")

    return [
        html_artifact(out_html, "Possible Duplicate People", note=f"{row_count} pairs", primary=True),
        csv_artifact(out_csv, "Duplicates (CSV)", note=f"{row_count} rows"),
    ]


REPORT = Report(
    id="duplicates",
    title="Possible Duplicate People",
    description=("Finds pairs of people in the tree who are probably the same person entered "
                "twice -- matching on name, dates, places, parents, children and spouses -- and "
                "ranks the pairs by confidence so the most likely duplicates surface first."),
    run=run,
    params=[
        Param("score_threshold", "Score threshold", "int", 70,
             "Minimum match score (0-100+) for a pair to be reported. Higher means fewer, "
             "stronger matches.", min=0, max=200),
        Param("birth_window_years", "Birth year window", "int", 5,
             "Two people are only compared if their birth years are within this many years "
             "of each other.", min=0, max=50),
    ],
    needs_master_csv=True,
    needs_target=False,
    group="Quality",
    order=30,
)
