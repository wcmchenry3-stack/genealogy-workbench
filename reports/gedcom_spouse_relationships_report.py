#!/usr/bin/env python
# coding: utf-8
from __future__ import annotations

# In[ ]:


#!/usr/bin/env python3
# coding: utf-8
"""
gedcom_spouse_relationships_report.py
------------------------------------
Core logic for "spouse relationships" (consanguinity) report.

IMPORTANT DESIGN CHOICE
-----------------------
This report infers "spouse pairs" from (FatherID, MotherID) on child rows
in master_tree.csv (i.e., co-parents). That means:
  - couples with no recorded children will not appear
  - blended families will create multiple pairs

Output
------
CSV with one row per inferred couple, including:
  - inferred evidence (shared children count)
  - closest relationship label (e.g., 3C, 3C1R)
  - MRCA(s) for the closest relationship
  - all common ancestors found (as a compact list)
"""


import csv
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


# -----------------------------
# Data model
# -----------------------------
@dataclass(frozen=True)
class Person:
    id: str
    name: str
    father_id: str
    mother_id: str


# -----------------------------
# CSV loading
# -----------------------------
def _get(row: dict, *keys: str) -> str:
    """Return first non-empty field among keys."""
    for k in keys:
        v = (row.get(k) or "").strip()
        if v:
            return v
    return ""


def load_people(master_csv: str) -> Dict[str, Person]:
    """Load people from master_tree.csv into an ID->Person map."""
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
            )
    return people


# -----------------------------
# Ancestor traversal
# -----------------------------
def ancestor_depth_map(
    person_id: str,
    people: Dict[str, Person],
    max_depth: int,
) -> Dict[str, int]:
    """
    Return ancestor_id -> min generation depth (1=parent, 2=grandparent,...).
    Cycle-safe.
    """
    out: Dict[str, int] = {}
    if not person_id or person_id not in people or max_depth <= 0:
        return out

    q: deque[Tuple[str, int]] = deque()
    start = people[person_id]
    # seed with parents
    if start.father_id:
        q.append((start.father_id, 1))
    if start.mother_id:
        q.append((start.mother_id, 1))

    while q:
        cur_id, depth = q.popleft()
        if not cur_id:
            continue
        if depth > max_depth:
            continue
        # Keep the minimum depth if encountered multiple times
        prev = out.get(cur_id)
        if prev is not None and prev <= depth:
            continue
        out[cur_id] = depth

        cur = people.get(cur_id)
        if not cur:
            continue
        # expand upward
        if cur.father_id:
            q.append((cur.father_id, depth + 1))
        if cur.mother_id:
            q.append((cur.mother_id, depth + 1))

    return out


# -----------------------------
# Relationship labeling
# -----------------------------
def relationship_label_from_depths(d1: int, d2: int) -> str:
    """
    Convert generation depths to a relationship label.
    d1/d2 are generations from each spouse up to the *same* common ancestor.

    Conventions:
      - If d1==1 and d2==1 => Siblings (common parent)
      - If min(d1,d2)==1 and max>1 => Aunt/Uncle-style; label as 'AVUNCULAR'
      - Else => cousin/removed: degree=min(d1,d2)-1, removed=abs(d1-d2)
    """
    if d1 <= 0 or d2 <= 0:
        return "UNKNOWN"
    if d1 == 1 and d2 == 1:
        return "SIBLINGS"
    if min(d1, d2) == 1 and max(d1, d2) > 1:
        # One spouse is closer to the common ancestor by being their descendant's parent line.
        # Example: d1=1, d2=3 => spouse1 shares a parent with spouse2's grandparent line.
        return f"AVUNCULAR(d1={d1},d2={d2})"

    degree = min(d1, d2) - 1
    removed = abs(d1 - d2)
    if degree <= 0:
        return f"RELATED(d1={d1},d2={d2})"

    if removed == 0:
        return f"{degree}C"
    if removed == 1:
        return f"{degree}C1R"
    return f"{degree}C{removed}R"


def _compare_common(d1: int, d2: int) -> Tuple[int, int, int]:
    """Sorting key: prefer smallest max depth, then smallest removal, then smallest sum."""
    return (max(d1, d2), abs(d1 - d2), d1 + d2)


# -----------------------------
# Couple inference
# -----------------------------
@dataclass
class CoupleEvidence:
    p1: str
    p2: str
    shared_children: List[str]  # child IDs
    shared_children_names: List[str]  # child names (parallel)

    def add_child(self, cid: str, cname: str) -> None:
        # keep lists small but informative
        self.shared_children.append(cid)
        self.shared_children_names.append(cname)

    @property
    def count(self) -> int:
        return len(self.shared_children)


def infer_couples_from_children(master_csv: str) -> Dict[Tuple[str, str], CoupleEvidence]:
    """Infer parent pairs from child rows in master_tree.csv."""
    couples: Dict[Tuple[str, str], CoupleEvidence] = {}

    with open(master_csv, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            child_id = _get(row, "ID", "Id", "PersonID", "person_id")
            child_name = _get(row, "Name", "FullName", "full_name") or child_id

            father = _get(row, "FatherID", "Father", "father_id")
            mother = _get(row, "MotherID", "Mother", "mother_id")
            if not father or not mother:
                continue

            # Canonical key for dedupe (order-independent)
            k = (father, mother) if father < mother else (mother, father)

            ev = couples.get(k)
            if ev is None:
                ev = CoupleEvidence(p1=k[0], p2=k[1], shared_children=[], shared_children_names=[])
                couples[k] = ev

            # Keep a limited sample to avoid huge CSV cells
            if ev.count < 20:
                ev.add_child(child_id, child_name)

    return couples


# -----------------------------
# Report generation
# -----------------------------
def generate_spouse_relationships_report(
    *,
    master_csv: str,
    out_csv: str,
    max_depth: int = 12,
) -> None:
    """Generate the spouse relationship report."""
    people = load_people(master_csv)
    couples = infer_couples_from_children(master_csv)

    out_path = Path(out_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "Parent1ID",
        "Parent1Name",
        "Parent2ID",
        "Parent2Name",
        "SharedChildrenCount",
        "SharedChildrenSample",
        "ClosestRelationship",
        "ClosestMRCA_IDs",
        "ClosestMRCA_Names",
        "ClosestDepths",
        "AllCommonAncestors",
        "Status",
    ]

    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()

        for (p1, p2), ev in sorted(couples.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            p1_name = people.get(p1).name if p1 in people else p1
            p2_name = people.get(p2).name if p2 in people else p2

            # Build ancestor maps
            a1 = ancestor_depth_map(p1, people, max_depth=max_depth)
            a2 = ancestor_depth_map(p2, people, max_depth=max_depth)

            status = "OK"
            closest_rel = "NONE"
            closest_mrca_ids: List[str] = []
            closest_mrca_names: List[str] = []
            closest_depths = ""
            all_common = ""

            # Direct ancestor checks (rare but possible)
            if p1 in a2:
                d = a2[p1]
                closest_rel = f"DIRECT_ANCESTOR(p1_is_ancestor_depth={d})"
                closest_mrca_ids = [p1]
                closest_mrca_names = [p1_name]
                closest_depths = f"(p1_depth_in_p2_tree={d})"
                status = "DIRECT_ANCESTOR"
            elif p2 in a1:
                d = a1[p2]
                closest_rel = f"DIRECT_ANCESTOR(p2_is_ancestor_depth={d})"
                closest_mrca_ids = [p2]
                closest_mrca_names = [p2_name]
                closest_depths = f"(p2_depth_in_p1_tree={d})"
                status = "DIRECT_ANCESTOR"
            else:
                commons = set(a1.keys()) & set(a2.keys())
                if not commons:
                    status = "NO_COMMON_ANCESTOR"
                else:
                    # Compute and sort all common ancestors
                    items: List[Tuple[Tuple[int, int, int], str, int, int]] = []
                    for anc in commons:
                        d1 = a1[anc]
                        d2 = a2[anc]
                        items.append((_compare_common(d1, d2), anc, d1, d2))
                    items.sort(key=lambda t: t[0])

                    # Closest key is the first
                    best_key = items[0][0]
                    best = [(anc, d1, d2) for (k, anc, d1, d2) in items if k == best_key]

                    # Relationship label computed from the best depths (if multiple, should match)
                    best_d1, best_d2 = best[0][1], best[0][2]
                    closest_rel = relationship_label_from_depths(best_d1, best_d2)
                    closest_depths = f"d1={best_d1};d2={best_d2}"

                    closest_mrca_ids = [anc for (anc, _, _) in best]
                    closest_mrca_names = [
                        (people.get(anc).name if anc in people else anc) for anc in closest_mrca_ids
                    ]

                    # All common ancestors (compact list)
                    # Format: ANC_ID|d1|d2|Name
                    parts: List[str] = []
                    for _, anc, d1, d2 in items:
                        nm = people.get(anc).name if anc in people else anc
                        parts.append(f"{anc}|{d1}|{d2}|{nm}")
                    all_common = ";".join(parts)

            child_sample = ", ".join(
                f"{cid}({cname})" for cid, cname in zip(ev.shared_children, ev.shared_children_names)
            )
            w.writerow(
                {
                    "Parent1ID": p1,
                    "Parent1Name": p1_name,
                    "Parent2ID": p2,
                    "Parent2Name": p2_name,
                    "SharedChildrenCount": ev.count,
                    "SharedChildrenSample": child_sample,
                    "ClosestRelationship": closest_rel,
                    "ClosestMRCA_IDs": ",".join(closest_mrca_ids),
                    "ClosestMRCA_Names": ",".join(closest_mrca_names),
                    "ClosestDepths": closest_depths,
                    "AllCommonAncestors": all_common,
                    "Status": status,
                }
            )
