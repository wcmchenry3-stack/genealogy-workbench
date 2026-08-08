#!/usr/bin/env python3
"""
reports/registry.py
-------------------
The list of reports the application offers.

This file is deliberately flat and unordered by origin. Every entry is just a
report. Add a module exposing `REPORT` and list it here; it shows up in the UI
with its parameters, and the runner works out what data it needs.
"""
from __future__ import annotations

from .base import Report

from .r_timelines import REPORT as TIMELINES
from .r_locations import REPORT as LOCATIONS
from .r_map import REPORT as MAP
from .r_tree import REPORT as TREE
from .r_immigrants import REPORT as IMMIGRANTS
from .r_spouses import REPORT as SPOUSES
from .r_diagnostics import REPORT as DIAGNOSTICS
from .r_duplicates import REPORT as DUPLICATES

ALL_REPORTS: list[Report] = [
    TIMELINES, LOCATIONS, MAP, TREE, IMMIGRANTS, SPOUSES, DIAGNOSTICS, DUPLICATES,
]

BY_ID: dict[str, Report] = {r.id: r for r in ALL_REPORTS}


def get(report_id: str) -> Report:
    return BY_ID[report_id]


def resolve_selection(ids: list[str]) -> list[Report]:
    """Expand a user selection to include prerequisites, in a runnable order.

    The map deep-links into the Locations report, so picking the map implicitly
    picks Locations too. Reports declare this with `requires`; nobody has to
    remember it.
    """
    wanted, seen = [], set()

    def add(rid: str):
        if rid in seen or rid not in BY_ID:
            return
        seen.add(rid)
        for dep in BY_ID[rid].requires:
            add(dep)          # prerequisites are appended before their dependent
        wanted.append(BY_ID[rid])

    # Sort the *requested* ids for a predictable sequence, then expand. The result
    # must not be re-sorted afterwards: that could place a report ahead of the
    # prerequisite it reads from, which is how the map would end up with dead
    # links into a Locations report that had not been written yet.
    for rid in sorted(ids, key=lambda i: (BY_ID[i].order, BY_ID[i].title) if i in BY_ID else (999, i)):
        add(rid)
    return wanted


def needs_pipeline(reports: list[Report]) -> tuple[bool, bool]:
    """(needs events.csv, needs master_tree.csv) for a set of reports."""
    return (any(r.needs_events for r in reports),
            any(r.needs_master_csv for r in reports))
