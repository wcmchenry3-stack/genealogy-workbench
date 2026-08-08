#!/usr/bin/env python
# coding: utf-8
from __future__ import annotations

# In[ ]:


#!/usr/bin/env python3
# coding: utf-8
"""
gedcom_analyzer.py
-------------------
Run diagnostics on master_tree.csv for a selected focus root_id.

Milestone 4 refactor:
- Separate data loading, traversal, and tests
- Keep public API: run_diagnostics(master_csv_path, output_csv_path, root_id, max_gens)
"""


import csv
import math
import re
from typing import Dict, Set, Optional, Tuple


_YEAR_RE = re.compile(r"\b(\d{4})\b")


def haversine(lat1, lon1, lat2, lon2) -> float:
    """
    Distance in miles.
    """
    R = 3958.7613
    p = math.pi / 180.0
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(min(1, math.sqrt(a)))
    return R * c


def _year_from_clean_date(s: str) -> Optional[int]:
    if not s:
        return None
    m = _YEAR_RE.search(str(s))
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _load_people(master_csv_path: str) -> Dict[str, dict]:
    people: Dict[str, dict] = {}
    with open(master_csv_path, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            pid = row.get("ID")
            if pid:
                people[pid] = row
    return people


def _collect_relevant_ids(people: Dict[str, dict], root_id: str, max_gens: int) -> Set[str]:
    """
    Collect all ancestors up to max_gens (inclusive):
      root at gen=0
      parents gen=1
      ...
    """
    relevant: Set[str] = set()
    queue: list[tuple[str, int]] = [(root_id, 0)]

    while queue:
        pid, gen = queue.pop(0)
        if not pid or pid not in people:
            continue
        if gen > max_gens:
            continue
        if pid in relevant:
            continue

        relevant.add(pid)

        row = people[pid]
        father = (row.get("FatherID") or "").strip()
        mother = (row.get("MotherID") or "").strip()

        if father:
            queue.append((father, gen + 1))
        if mother:
            queue.append((mother, gen + 1))

    return relevant


def _lifespan_checks(child: dict, parent: dict, rel: str) -> Tuple[str, str]:
    """
    Restores original lifespan rules:
      - Parent too young (<16) if both parent + child birth years known
      - Mother died before birth
      - Father died >1yr before birth
    Returns: (status, note)
    """
    c_birth_year = _year_from_clean_date(child.get("BirtDate_Clean") or child.get("BirthDate_Clean") or "")
    p_birth_year = _year_from_clean_date(parent.get("BirtDate_Clean") or parent.get("BirthDate_Clean") or "")
    p_death_year = _year_from_clean_date(parent.get("DeatDate_Clean") or parent.get("DeathDate_Clean") or "")

    if c_birth_year is None:
        return ("SKIP", "No Child DOB")

    # Too young check only needs parent birth year
    if p_birth_year is not None:
        age = c_birth_year - p_birth_year
        if age < 16:
            return ("FAIL", f"Parent too young ({int(age)})")

    # Death-before-birth checks do NOT require parent DOB
    if p_death_year is not None:
        if rel == "Mother" and p_death_year < c_birth_year:
            return ("FAIL", "Mother died before birth")
        if rel == "Father" and p_death_year < (c_birth_year - 1):
            return ("FAIL", "Father died >1yr before birth")

    return ("PASS", "")


def _geo_checks(child: dict, parent: dict) -> Tuple[str, str]:
    """
    Geography heuristic:
      - if child birth lat/lon & parent birth lat/lon exist: distance should not be huge
      - likewise child death vs parent death
    Returns: (status, note)
    """
    def _flt(x: str) -> Optional[float]:
        try:
            return float(x)
        except Exception:
            return None

    c_bl = _flt(child.get("BirtLat") or "")
    c_blo = _flt(child.get("BirtLon") or "")
    c_dl = _flt(child.get("DeatLat") or "")
    c_dlo = _flt(child.get("DeatLon") or "")

    p_bl = _flt(parent.get("BirtLat") or "")
    p_blo = _flt(parent.get("BirtLon") or "")
    p_dl = _flt(parent.get("DeatLat") or "")
    p_dlo = _flt(parent.get("DeatLon") or "")

    # If child missing birth coords entirely, skip (original intent)
    if c_bl is None or c_blo is None:
        return ("SKIP", "Child loc unmapped")

    # Thresholds (unchanged feel)
    max_birth_miles = 250.0
    max_death_miles = 500.0

    # Birth distance
    dist_b = None
    if p_bl is not None and p_blo is not None:
        dist_b = haversine(c_bl, c_blo, p_bl, p_blo)

    # Death distance
    dist_d = None
    if c_dl is not None and c_dlo is not None and p_dl is not None and p_dlo is not None:
        dist_d = haversine(c_dl, c_dlo, p_dl, p_dlo)

    # Decide
    if dist_b is not None and dist_b > max_birth_miles:
        return ("WARN", f"Too far: Parent B ({int(dist_b)}mi)")

    if dist_d is not None and dist_d > max_death_miles:
        return ("WARN", f"Too far: Parent D ({int(dist_d)}mi)")

    return ("PASS", "")


def run_diagnostics(master_csv_path: str, output_csv_path: str, root_id: str, max_gens: int) -> None:
    """
    Public API (unchanged).
    """
    people = _load_people(master_csv_path)
    relevant_ids = _collect_relevant_ids(people, root_id, max_gens)

    fieldnames = ["Test Type", "Result", "Child", "Parent", "Notes", "Detail"]
    with open(output_csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()

        for pid in sorted(relevant_ids):
            child = people.get(pid)
            if not child:
                continue

            for rel, key in (("Father", "FatherID"), ("Mother", "MotherID")):
                par_id = (child.get(key) or "").strip()
                if not par_id or par_id not in people:
                    continue
                parent = people[par_id]

                # Lifespan test
                life_stat, life_note = _lifespan_checks(child, parent, rel)
                w.writerow({
                    "Test Type": "Lifespan",
                    "Result": life_stat,
                    "Child": child.get("Name", ""),
                    "Parent": parent.get("Name", ""),
                    "Notes": life_note,
                    "Detail": rel,
                })

                # Geography test
                geo_stat, geo_note = _geo_checks(child, parent)
                w.writerow({
                    "Test Type": "Geography",
                    "Result": geo_stat,
                    "Child": child.get("Name", ""),
                    "Parent": parent.get("Name", ""),
                    "Notes": geo_note,
                    "Detail": rel,
                })
