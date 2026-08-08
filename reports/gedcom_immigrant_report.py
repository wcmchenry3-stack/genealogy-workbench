#!/usr/bin/env python
# coding: utf-8
from __future__ import annotations

# In[ ]:


#!/usr/bin/env python3
# coding: utf-8
"""
gedcom_immigrant_report.py
--------------------------
Core logic for the immigrant "exit from the US" report.

Definition (per-branch):
  - Start from focus person
  - Explore every ancestral branch upward
  - For each branch/path, find the FIRST ancestor whose birth place is outside the United States.
  - Stop that branch at that ancestor and record it as the 'exit point'.
  - If the branch ends (no parents) without finding a non-US birthplace, record as END-OF-BRANCH.
  - Birthplace 'unknown' does not stop traversal; we keep going upward if parents exist.

Output:
  - CSV with one row per branch result.
"""


import csv
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# -----------------------------
# Data model
# -----------------------------
@dataclass(frozen=True)
class Person:
    id: str
    name: str
    father_id: str
    mother_id: str
    birt_place: str
    birt_place_clean: str


# -----------------------------
# Helpers
# -----------------------------
def _get(row: dict, *keys: str) -> str:
    for k in keys:
        v = (row.get(k) or "").strip()
        if v:
            return v
    return ""


US_STATE_NAMES = {
    "alabama","alaska","arizona","arkansas","california","colorado","connecticut","delaware",
    "florida","georgia","hawaii","idaho","illinois","indiana","iowa","kansas","kentucky",
    "louisiana","maine","maryland","massachusetts","michigan","minnesota","mississippi",
    "missouri","montana","nebraska","nevada","new hampshire","new jersey","new mexico",
    "new york","north carolina","north dakota","ohio","oklahoma","oregon","pennsylvania",
    "rhode island","south carolina","south dakota","tennessee","texas","utah","vermont",
    "virginia","washington","west virginia","wisconsin","wyoming",
    "district of columbia",
}
US_TERRITORIES = {"puerto rico","guam","american samoa","u.s. virgin islands","virgin islands","northern mariana islands"}
US_MARKERS = {
    "united states","united states of america","usa","u.s.a","u.s.","us",
}


def is_us_birthplace(place: str) -> Optional[bool]:
    """
    Return True if place looks like US, False if clearly non-US, None if unknown/ambiguous.
    Conservative: prefers returning None over wrong classification.
    """
    s = (place or "").strip()
    if not s:
        return None
    low = s.lower()

    # Strong markers
    for m in US_MARKERS:
        if m in low:
            return True

    # Territories treated as US for this report unless you decide otherwise later
    for t in US_TERRITORIES:
        if t in low:
            return True

    # Look for state names (often "City, State" with no country)
    for st in US_STATE_NAMES:
        if st in low:
            return True

    # If there is an explicit country at the end that isn't US markers, treat as non-US.
    # Heuristic: last comma-separated token often a country
    parts = [p.strip().lower() for p in low.split(",") if p.strip()]
    if parts:
        last = parts[-1]
        if last in US_MARKERS or last in US_STATE_NAMES:
            return True
        # Common non-US country tokens. This is not exhaustive; we only use it to return False with confidence.
        NON_US_HINTS = {
            "england","scotland","wales","ireland","uk","u.k.","united kingdom","great britain",
            "canada","india","germany","france","italy","mexico","china","japan","russia",
            "australia","new zealand","sweden","norway","denmark","netherlands","belgium","spain",
            "portugal","switzerland","austria","poland","hungary","czech","slovakia","romania",
            "bulgaria","greece","turkey","israel","palestine","egypt","south africa","nigeria",
            "brazil","argentina","chile","peru","colombia",
        }
        if last in NON_US_HINTS:
            return False

    # Ambiguous -> unknown
    return None


def load_people(master_csv: str) -> Dict[str, Person]:
    people: Dict[str, Person] = {}
    with open(master_csv, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = _get(row, "ID", "Id", "PersonID", "person_id")
            if not pid:
                continue
            people[pid] = Person(
                id=pid,
                name=_get(row, "Name", "FullName", "full_name") or pid,
                father_id=_get(row, "FatherID", "Father", "father_id"),
                mother_id=_get(row, "MotherID", "Mother", "mother_id"),
                birt_place=_get(row, "BirtPlace"),
                birt_place_clean=_get(row, "BirtPlace_Clean"),
            )
    return people


def _format_path(path: List[Tuple[str, str]]) -> str:
    """path is list of (role, person_id) starting after focus."""
    return ">".join(f"{role}:{pid}" for role, pid in path)


def _format_name_path(focus_name: str, people: Dict[str, Person], path: List[Tuple[str, str]]) -> str:
    parts = [focus_name]
    for role, pid in path:
        nm = people.get(pid).name if pid in people else pid
        parts.append(f"{role}={nm}")
    return " -> ".join(parts)


# -----------------------------
# Report generation
# -----------------------------
def generate_immigrant_exit_report(
    *,
    master_csv: str,
    out_csv: str,
    root_id: str,
    max_gens: int = 12,
) -> None:
    people = load_people(master_csv)
    out_path = Path(out_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    focus = people.get(root_id)
    if not focus:
        raise ValueError(f"Focus/root_id not found in master CSV: {root_id}")

    headers = [
        "FocusID",
        "FocusName",
        "ExitType",
        "ExitPersonID",
        "ExitPersonName",
        "ExitBirthPlace",
        "ExitBirthPlace_Clean",
        "ExitDepth",
        "PathRolesIDs",
        "PathNames",
        "Notes",
    ]

    # Each queue state is: current_person_id, depth, path(list of (role, id))
    # depth is generations from focus (1=parent).
    q: deque[Tuple[str, int, List[Tuple[str, str]]]] = deque()

    if focus.father_id:
        q.append((focus.father_id, 1, [("Father", focus.father_id)]))
    if focus.mother_id:
        q.append((focus.mother_id, 1, [("Mother", focus.mother_id)]))

    results: List[dict] = []
    seen_branch_terminations: Set[str] = set()

    while q:
        cur_id, depth, path = q.popleft()

        # avoid pathological depth
        if max_gens is not None and depth > max_gens:
            # terminate this branch at last known node
            key = _format_path(path)
            if key in seen_branch_terminations:
                continue
            seen_branch_terminations.add(key)
            last = people.get(cur_id)
            results.append(
                {
                    "FocusID": root_id,
                    "FocusName": focus.name,
                    "ExitType": "MAX_DEPTH",
                    "ExitPersonID": cur_id,
                    "ExitPersonName": (last.name if last else cur_id),
                    "ExitBirthPlace": (last.birt_place if last else ""),
                    "ExitBirthPlace_Clean": (last.birt_place_clean if last else ""),
                    "ExitDepth": depth,
                    "PathRolesIDs": key,
                    "PathNames": _format_name_path(focus.name, people, path),
                    "Notes": f"Reached max_gens={max_gens} without finding foreign-born",
                }
            )
            continue

        # cycle protection: if cur_id appears earlier in the path (excluding last element)
        earlier_ids = [pid for (_, pid) in path[:-1]]
        if cur_id in earlier_ids:
            key = _format_path(path)
            if key in seen_branch_terminations:
                continue
            seen_branch_terminations.add(key)
            last = people.get(cur_id)
            results.append(
                {
                    "FocusID": root_id,
                    "FocusName": focus.name,
                    "ExitType": "CYCLE",
                    "ExitPersonID": cur_id,
                    "ExitPersonName": (last.name if last else cur_id),
                    "ExitBirthPlace": (last.birt_place if last else ""),
                    "ExitBirthPlace_Clean": (last.birt_place_clean if last else ""),
                    "ExitDepth": depth,
                    "PathRolesIDs": key,
                    "PathNames": _format_name_path(focus.name, people, path),
                    "Notes": "Detected cycle in ancestry links; branch stopped",
                }
            )
            continue

        person = people.get(cur_id)
        if not person:
            # missing person row in CSV
            key = _format_path(path)
            if key in seen_branch_terminations:
                continue
            seen_branch_terminations.add(key)
            results.append(
                {
                    "FocusID": root_id,
                    "FocusName": focus.name,
                    "ExitType": "MISSING_PERSON",
                    "ExitPersonID": cur_id,
                    "ExitPersonName": cur_id,
                    "ExitBirthPlace": "",
                    "ExitBirthPlace_Clean": "",
                    "ExitDepth": depth,
                    "PathRolesIDs": key,
                    "PathNames": _format_name_path(focus.name, people, path),
                    "Notes": "Person ID not present in master CSV; branch ended",
                }
            )
            continue

        place_candidate = person.birt_place_clean or person.birt_place
        us = is_us_birthplace(place_candidate)

        if us is False:
            # Found exit point for this branch
            key = _format_path(path)
            if key in seen_branch_terminations:
                continue
            seen_branch_terminations.add(key)
            results.append(
                {
                    "FocusID": root_id,
                    "FocusName": focus.name,
                    "ExitType": "FOUND_FOREIGN_BORN",
                    "ExitPersonID": person.id,
                    "ExitPersonName": person.name,
                    "ExitBirthPlace": person.birt_place,
                    "ExitBirthPlace_Clean": person.birt_place_clean,
                    "ExitDepth": depth,
                    "PathRolesIDs": key,
                    "PathNames": _format_name_path(focus.name, people, path),
                    "Notes": "",
                }
            )
            continue

        # If no parents, branch ends here with no foreign-born found
        if not person.father_id and not person.mother_id:
            key = _format_path(path)
            if key in seen_branch_terminations:
                continue
            seen_branch_terminations.add(key)
            note = "No parents recorded"
            if us is None:
                note += "; birthplace unknown/ambiguous"
            results.append(
                {
                    "FocusID": root_id,
                    "FocusName": focus.name,
                    "ExitType": "END_OF_BRANCH",
                    "ExitPersonID": person.id,
                    "ExitPersonName": person.name,
                    "ExitBirthPlace": person.birt_place,
                    "ExitBirthPlace_Clean": person.birt_place_clean,
                    "ExitDepth": depth,
                    "PathRolesIDs": key,
                    "PathNames": _format_name_path(focus.name, people, path),
                    "Notes": note,
                }
            )
            continue

        # Otherwise keep traversing upward.
        if person.father_id:
            q.append((person.father_id, depth + 1, path + [("Father", person.father_id)]))
        if person.mother_id:
            q.append((person.mother_id, depth + 1, path + [("Mother", person.mother_id)]))

    # Write results
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in results:
            w.writerow(r)
