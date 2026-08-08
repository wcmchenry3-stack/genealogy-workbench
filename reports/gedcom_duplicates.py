#!/usr/bin/env python
# coding: utf-8
from __future__ import annotations

# In[ ]:


#!/usr/bin/env python3
# coding: utf-8
"""
gedcom_duplicates.py
--------------------
Detect probable duplicate individuals in master_tree.csv.

Milestone 4 refactor:
- Organize into DuplicateDetector class (config + orchestration)
- Keep public API: run_duplicate_detection(...)
- Keep CLI behavior
"""


import csv
import re
import difflib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# Optional acceleration
try:
    from rapidfuzz import fuzz  # type: ignore
    _HAS_RAPIDFUZZ = True
except Exception:
    _HAS_RAPIDFUZZ = False


# ----------------------------
# Defaults / Weights (unchanged intent)
# ----------------------------
DEFAULT_SCORE_THRESHOLD = 70
DEFAULT_BIRTH_WINDOW_YEARS = 5

W_NAME_EXACT = 55
W_NAME_STRONG = 40
W_NAME_WEAK = 20

W_BIRTH_EXACT = 25
W_BIRTH_NEAR = 15
W_BIRTH_CONFLICT = -25

W_DEATH_EXACT = 15
W_DEATH_NEAR = 8
W_DEATH_CONFLICT = -15

W_PLAC_STRONG = 15
W_PLAC_WEAK = 8
W_PLAC_CONFLICT = -10

W_PARENTS_BOTH = 40
W_PARENTS_ONE = 25
W_PARENTS_MISSING = 10
W_PARENTS_CONFLICT = -25

W_CHILDREN_STRONG = 25
W_CHILDREN_WEAK = 10

W_SPOUSE_MATCH = 30
W_SPOUSE_PRESENT_CONFLICT = -15
W_SPOUSE_PARTIAL = 10


# ----------------------------
# Utilities: parsing & normalization
# ----------------------------
_YEAR_RE = re.compile(r"\b(\d{4})\b")


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


def _date_range_from_clean(s: str) -> Optional[Tuple[int, int]]:
    """
    Accepts:
      - 'YYYY'
      - 'YYYY-YYYY'
      - strings containing a year (takes that year)
    Returns (min_year, max_year)
    """
    if not s:
        return None

    s = str(s).strip()
    # Direct range
    if "-" in s:
        parts = [p.strip() for p in s.split("-") if p.strip()]
        if len(parts) >= 2:
            y1 = _year_from_clean_date(parts[0])
            y2 = _year_from_clean_date(parts[1])
            if y1 and y2:
                lo, hi = min(y1, y2), max(y1, y2)
                return (lo, hi)

    y = _year_from_clean_date(s)
    if y is None:
        return None
    return (y, y)


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _parse_name_simple(name_raw: str) -> Tuple[str, str]:
    """
    GEDCOM names often look like: 'John /Smith/'
    Return: (given, surname) in lowercase-ish normalized forms.
    """
    s = _normalize_spaces(name_raw).replace('"', "")
    if "/" in s:
        parts = [p.strip() for p in s.split("/") if p.strip()]
        if len(parts) >= 2:
            given = parts[0]
            surname = parts[1]
            return (given.lower(), surname.lower())
    # fallback: last token surname heuristic
    tokens = s.split()
    if not tokens:
        return ("", "")
    if len(tokens) == 1:
        return (tokens[0].lower(), "")
    return (" ".join(tokens[:-1]).lower(), tokens[-1].lower())


def _given_key(given: str) -> str:
    g = re.sub(r"[^a-z]", "", (given or "").lower())
    if not g:
        return ""
    # lightweight blocking key: first 4 letters
    return g[:4]


def _ratio(a: str, b: str) -> int:
    a = (a or "").lower().strip()
    b = (b or "").lower().strip()
    if not a or not b:
        return 0
    if _HAS_RAPIDFUZZ:
        return int(fuzz.token_set_ratio(a, b))
    return int(difflib.SequenceMatcher(None, a, b).ratio() * 100)


def _ranges_overlap(a: Tuple[int, int], b: Tuple[int, int]) -> bool:
    return max(a[0], b[0]) <= min(a[1], b[1])


def _range_mid(r: Optional[Tuple[int, int]]) -> Optional[int]:
    if not r:
        return None
    return (r[0] + r[1]) // 2


# ----------------------------
# Data model
# ----------------------------
@dataclass
class DupPerson:
    id: str
    name_raw: str
    given: str
    surname: str
    sex: str = ""
    birth_range: Optional[Tuple[int, int]] = None
    death_range: Optional[Tuple[int, int]] = None
    birth_place: str = ""
    death_place: str = ""

    father_id: str = ""
    mother_id: str = ""

    children_ids: Set[str] = field(default_factory=set)
    spouse_ids: Set[str] = field(default_factory=set)


@dataclass
class ScoreBreakdown:
    total: int = 0
    name: int = 0
    birth: int = 0
    death: int = 0
    places: int = 0
    parents: int = 0
    children: int = 0
    spouses: int = 0
    notes: str = ""


# ----------------------------
# Hard gates (impossibilities only)
# ----------------------------
def _hard_gate(a: DupPerson, b: DupPerson) -> bool:
    if a.sex and b.sex and a.sex != b.sex:
        return False
    return True


def _birth_window_ok(a: DupPerson, b: DupPerson, birth_window_years: int) -> bool:
    ra = a.birth_range
    rb = b.birth_range
    if not ra or not rb:
        return True
    ma = _range_mid(ra)
    mb = _range_mid(rb)
    if ma is None or mb is None:
        return True
    return abs(ma - mb) <= birth_window_years


# ----------------------------
# Scoring
# ----------------------------
def _score_pair(a: DupPerson, b: DupPerson) -> ScoreBreakdown:
    score = ScoreBreakdown(total=0)

    # ---- Name ----
    gsim = _ratio(a.given, b.given)
    nsim = _ratio(a.name_raw, b.name_raw)

    if nsim >= 95:
        score.name = W_NAME_EXACT
    elif gsim >= 90 or nsim >= 88:
        score.name = W_NAME_STRONG
    elif gsim >= 75 or nsim >= 75:
        score.name = W_NAME_WEAK
    else:
        score.name = 0

    # ---- Birth year ----
    if a.birth_range and b.birth_range:
        if _ranges_overlap(a.birth_range, b.birth_range):
            # exact vs near based on midpoint distance
            ma = _range_mid(a.birth_range)
            mb = _range_mid(b.birth_range)
            if ma is not None and mb is not None and abs(ma - mb) <= 1:
                score.birth = W_BIRTH_EXACT
            else:
                score.birth = W_BIRTH_NEAR
        else:
            score.birth = W_BIRTH_CONFLICT

    # ---- Death year ----
    if a.death_range and b.death_range:
        if _ranges_overlap(a.death_range, b.death_range):
            ma = _range_mid(a.death_range)
            mb = _range_mid(b.death_range)
            if ma is not None and mb is not None and abs(ma - mb) <= 1:
                score.death = W_DEATH_EXACT
            else:
                score.death = W_DEATH_NEAR
        else:
            score.death = W_DEATH_CONFLICT

    # ---- Places ----
    bp_sim = _ratio(a.birth_place, b.birth_place) if a.birth_place and b.birth_place else 0
    dp_sim = _ratio(a.death_place, b.death_place) if a.death_place and b.death_place else 0
    best_place = max(bp_sim, dp_sim)

    if best_place >= 90:
        score.places = W_PLAC_STRONG
    elif best_place >= 75:
        score.places = W_PLAC_WEAK
    elif (a.birth_place and b.birth_place) or (a.death_place and b.death_place):
        # both have something but not similar
        score.places = W_PLAC_CONFLICT

    # ---- Parents ----
    parents_match = 0
    parents_conflict = 0

    # father
    if a.father_id and b.father_id:
        parents_match += (1 if a.father_id == b.father_id else 0)
        parents_conflict += (1 if a.father_id != b.father_id else 0)
    # mother
    if a.mother_id and b.mother_id:
        parents_match += (1 if a.mother_id == b.mother_id else 0)
        parents_conflict += (1 if a.mother_id != b.mother_id else 0)

    if parents_conflict:
        score.parents = W_PARENTS_CONFLICT
    else:
        if parents_match == 2:
            score.parents = W_PARENTS_BOTH
        elif parents_match == 1:
            score.parents = W_PARENTS_ONE
        else:
            # weak positive if both missing or partial (don’t punish)
            score.parents = W_PARENTS_MISSING

    # ---- Children ----
    if a.children_ids and b.children_ids:
        inter = a.children_ids.intersection(b.children_ids)
        if len(inter) >= 2:
            score.children = W_CHILDREN_STRONG
        elif len(inter) == 1:
            score.children = W_CHILDREN_WEAK

    # ---- Spouses ----
    if a.spouse_ids and b.spouse_ids:
        inter = a.spouse_ids.intersection(b.spouse_ids)
        if inter:
            score.spouses = W_SPOUSE_MATCH
        else:
            score.spouses = W_SPOUSE_PRESENT_CONFLICT
    elif (a.spouse_ids and not b.spouse_ids) or (b.spouse_ids and not a.spouse_ids):
        score.spouses = W_SPOUSE_PARTIAL

    score.total = (
        score.name + score.birth + score.death + score.places + score.parents + score.children + score.spouses
    )
    return score


# ----------------------------
# Blocking candidates
# ----------------------------
def _candidate_blocks(p: DupPerson) -> List[str]:
    blocks = []
    gk = _given_key(p.given)
    if gk:
        blocks.append(f"G:{gk}")
    if p.surname:
        blocks.append(f"S:{p.surname[:5]}")
    by = _range_mid(p.birth_range) if p.birth_range else None
    if by:
        blocks.append(f"Y:{by//10}")  # decade bucket
    return blocks or ["ALL"]


def _load_people_from_master_csv(master_csv_path: str) -> Dict[str, DupPerson]:
    people: Dict[str, DupPerson] = {}

    with open(master_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = (row.get("ID") or "").strip()
            if not pid:
                continue

            name_raw = (row.get("Name") or "").strip()
            given, surname = _parse_name_simple(name_raw)

            birth_range = _date_range_from_clean(row.get("BirthDate_Clean") or row.get("BirtDate_Clean") or row.get("birthdate_clean") or "")
            death_range = _date_range_from_clean(row.get("DeathDate_Clean") or row.get("DeatDate_Clean") or row.get("deathdate_clean") or "")

            birth_place = (row.get("BirthPlace_Clean") or row.get("BirtPlace_Clean") or row.get("birthplace_clean") or row.get("BirtPlace") or "").strip()
            death_place = (row.get("DeathPlace_Clean") or row.get("DeatPlace_Clean") or row.get("deathplace_clean") or row.get("DeatPlace") or "").strip()

            dp = DupPerson(
                id=pid,
                name_raw=name_raw,
                given=given,
                surname=surname,
                sex=(row.get("Sex") or "").strip(),
                birth_range=birth_range,
                death_range=death_range,
                birth_place=birth_place,
                death_place=death_place,
                father_id=(row.get("FatherID") or "").strip(),
                mother_id=(row.get("MotherID") or "").strip(),
            )
            people[pid] = dp

    # child relationships: build parent -> children sets
    for p in people.values():
        if p.father_id and p.father_id in people:
            people[p.father_id].children_ids.add(p.id)
        if p.mother_id and p.mother_id in people:
            people[p.mother_id].children_ids.add(p.id)

    return people


def _add_spouse_links_from_gedcom(people: Dict[str, DupPerson], gedcom_path: str) -> None:
    """
    Optional spouse links via families from GEDCOM.
    """
    try:
        from gedcom_parser import parse_gedcom
    except Exception as e:
        print(f"⚠️ Could not import gedcom_parser to add spouse links: {e}")
        return

    try:
        _inds, fams = parse_gedcom(gedcom_path)
    except Exception as e:
        print(f"⚠️ Could not parse GEDCOM for spouse links: {e}")
        return

    for fam in fams.values():
        h = getattr(fam, "husb", None)
        w = getattr(fam, "wife", None)
        if h and w and h in people and w in people:
            people[h].spouse_ids.add(w)
            people[w].spouse_ids.add(h)


# ----------------------------
# Detector orchestration
# ----------------------------
@dataclass
class DuplicateDetectorConfig:
    score_threshold: int = DEFAULT_SCORE_THRESHOLD
    birth_window_years: int = DEFAULT_BIRTH_WINDOW_YEARS
    max_pairs: Optional[int] = None
    gedcom_path_for_spouses: Optional[str] = None


class DuplicateDetector:
    def __init__(self, config: DuplicateDetectorConfig):
        self.config = config

    def run(self, master_csv_path: str, output_csv_path: str) -> None:
        people = _load_people_from_master_csv(master_csv_path)

        if self.config.gedcom_path_for_spouses:
            _add_spouse_links_from_gedcom(people, self.config.gedcom_path_for_spouses)

        # Build blocks
        block_index: Dict[str, List[str]] = {}
        for pid, p in people.items():
            for b in _candidate_blocks(p):
                block_index.setdefault(b, []).append(pid)

        results: List[Tuple[int, str, str, ScoreBreakdown]] = []
        seen_pairs: Set[Tuple[str, str]] = set()
        pairs_scored = 0

        # Score within blocks
        for _, ids in block_index.items():
            if len(ids) < 2:
                continue

            ids_sorted = sorted(ids)
            for i in range(len(ids_sorted)):
                for j in range(i + 1, len(ids_sorted)):
                    a_id, b_id = ids_sorted[i], ids_sorted[j]
                    key = (a_id, b_id)
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)

                    a = people[a_id]
                    b = people[b_id]

                    # Hard gates
                    if not _hard_gate(a, b):
                        continue
                    if not _birth_window_ok(a, b, self.config.birth_window_years):
                        continue

                    sb = _score_pair(a, b)
                    pairs_scored += 1

                    if sb.total >= self.config.score_threshold:
                        results.append((sb.total, a.id, b.id, sb))

                    if self.config.max_pairs is not None and pairs_scored >= self.config.max_pairs:
                        break
                if self.config.max_pairs is not None and pairs_scored >= self.config.max_pairs:
                    break
            if self.config.max_pairs is not None and pairs_scored >= self.config.max_pairs:
                break

        # Sort high-to-low
        results.sort(key=lambda t: t[0], reverse=True)

        # Write report
        fieldnames = [
            "Score", "A_ID", "B_ID", "A_Name", "B_Name",
            "A_Birth", "B_Birth", "A_Death", "B_Death",
            "A_BirthPlace", "B_BirthPlace", "A_DeathPlace", "B_DeathPlace",
            "NamePts", "BirthPts", "DeathPts", "PlacePts", "ParentsPts", "ChildrenPts", "SpousePts"
        ]

        with open(output_csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()

            for score_total, a_id, b_id, sb in results:
                a = people[a_id]
                b = people[b_id]
                w.writerow({
                    "Score": score_total,
                    "A_ID": a_id,
                    "B_ID": b_id,
                    "A_Name": a.name_raw,
                    "B_Name": b.name_raw,
                    "A_Birth": a.birth_range,
                    "B_Birth": b.birth_range,
                    "A_Death": a.death_range,
                    "B_Death": b.death_range,
                    "A_BirthPlace": a.birth_place,
                    "B_BirthPlace": b.birth_place,
                    "A_DeathPlace": a.death_place,
                    "B_DeathPlace": b.death_place,
                    "NamePts": sb.name,
                    "BirthPts": sb.birth,
                    "DeathPts": sb.death,
                    "PlacePts": sb.places,
                    "ParentsPts": sb.parents,
                    "ChildrenPts": sb.children,
                    "SpousePts": sb.spouses,
                })


def run_duplicate_detection(
    master_csv_path: str,
    output_csv_path: str,
    *,
    score_threshold: int = DEFAULT_SCORE_THRESHOLD,
    birth_window_years: int = DEFAULT_BIRTH_WINDOW_YEARS,
    max_pairs: Optional[int] = None,
    gedcom_path_for_spouses: Optional[str] = None,
) -> None:
    """
    Backward-compatible wrapper.
    """
    cfg = DuplicateDetectorConfig(
        score_threshold=score_threshold,
        birth_window_years=birth_window_years,
        max_pairs=max_pairs,
        gedcom_path_for_spouses=gedcom_path_for_spouses,
    )
    DuplicateDetector(cfg).run(master_csv_path, output_csv_path)


def _cli():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("master_csv")
    ap.add_argument("output_csv")
    ap.add_argument("--threshold", type=int, default=DEFAULT_SCORE_THRESHOLD)
    ap.add_argument("--birth-window", type=int, default=DEFAULT_BIRTH_WINDOW_YEARS)
    ap.add_argument("--max-pairs", type=int, default=None)
    ap.add_argument("--gedcom", type=str, default=None)
    args = ap.parse_args()

    run_duplicate_detection(
        args.master_csv,
        args.output_csv,
        score_threshold=args.threshold,
        birth_window_years=args.birth_window,
        max_pairs=args.max_pairs,
        gedcom_path_for_spouses=args.gedcom,
    )


if __name__ == "__main__":
    _cli()
