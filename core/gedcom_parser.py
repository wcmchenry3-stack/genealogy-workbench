#!/usr/bin/env python
# coding: utf-8
from __future__ import annotations

# In[ ]:


#!/usr/bin/env python3
# coding: utf-8
"""
gedcom_parser.py
----------------
GEDCOM parser producing:
  individuals: dict[id] -> Person
  families:    dict[id] -> Family

Fix:
- Correct GEDCOM level handling (BIRT/DEAT/MARR are level 1; DATE/PLAC are level 2)
- Reset active_tag on unrelated level-1 tags so RESI/BURI/etc can't overwrite BIRT/DEAT
- Keep public API: parse_gedcom(filename, show_progress=True)
"""


import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Iterable, Tuple

_LINE_RE = re.compile(r"^(\d+)\s+(@[^@]+@)?\s*([A-Z0-9_]+)\s*(.*)$")


@dataclass
class Person:
    id: str
    name: str = "Unknown"
    sex: str = ""
    birt_date: str = ""
    birt_place: str = ""
    deat_date: str = ""
    deat_place: str = ""
    marr_date: str = ""        # copied from spouse family post-process
    famc: str = ""             # family where they are a child
    fams: list[str] = field(default_factory=list)  # families where they are a spouse


@dataclass
class Family:
    id: str
    husb: Optional[str] = None
    wife: Optional[str] = None
    marr_date: str = ""
    marr_place: str = ""


def _iter_lines_with_optional_progress(filename: str, show_progress: bool):
    try:
        if show_progress:
            from tqdm import tqdm  # type: ignore
            with open(filename, "r", encoding="utf-8", errors="replace") as f:
                for line in tqdm(f, desc="Parsing GEDCOM", unit="lines"):
                    yield line.rstrip("\n")
        else:
            with open(filename, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    yield line.rstrip("\n")
    except Exception:
        with open(filename, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                yield line.rstrip("\n")


def parse_gedcom_core(lines: Iterable[str]) -> Tuple[Dict[str, Person], Dict[str, Family]]:
    individuals: Dict[str, Person] = {}
    families: Dict[str, Family] = {}

    current_record: Optional[object] = None  # Person | Family | None
    active_tag: Optional[str] = None         # "BIRT" | "DEAT" | "MARR" | None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        m = _LINE_RE.match(line)
        if not m:
            continue

        level_s, xref, tag, value = m.groups()
        level = int(level_s)
        tag = (tag or "").strip()
        value = (value or "").strip()

        # ------------------------------------------------------------
        # Level 0: start of a new record
        # ------------------------------------------------------------
        if level == 0:
            active_tag = None
            if tag == "INDI" and xref:
                pid = xref
                current_record = individuals.setdefault(pid, Person(id=pid))
            elif tag == "FAM" and xref:
                fid = xref
                current_record = families.setdefault(fid, Family(id=fid))
            else:
                current_record = None
            continue

        # If we aren't inside a record, ignore
        if current_record is None:
            continue

        # ------------------------------------------------------------
        # Level 1: properties / event headers (this is where active_tag changes)
        # ------------------------------------------------------------
        if level == 1:
            # Any new level-1 tag that isn't the current event header ends the old event context
            # (critical fix: RESI/BURI/etc will clear BIRT/DEAT context)
            if isinstance(current_record, Person):
                if tag == "NAME":
                    current_record.name = value or current_record.name
                    active_tag = None
                elif tag == "SEX":
                    current_record.sex = value
                    active_tag = None
                elif tag == "FAMC":
                    current_record.famc = value
                    active_tag = None
                elif tag == "FAMS":
                    if value:
                        current_record.fams.append(value)
                    active_tag = None
                elif tag in ("BIRT", "DEAT"):
                    active_tag = tag
                    # Optional: support inline value on the event line (nonstandard but seen in the wild)
                    # Example: "1 BIRT 20 Aug 1906"
                    if value:
                        if tag == "BIRT" and not current_record.birt_date:
                            current_record.birt_date = value
                        elif tag == "DEAT" and not current_record.deat_date:
                            current_record.deat_date = value
                else:
                    # Any other level-1 tag ends event context
                    active_tag = None

            elif isinstance(current_record, Family):
                if tag == "HUSB":
                    current_record.husb = value
                    active_tag = None
                elif tag == "WIFE":
                    current_record.wife = value
                    active_tag = None
                elif tag == "MARR":
                    active_tag = "MARR"
                    if value and not current_record.marr_date:
                        current_record.marr_date = value
                else:
                    active_tag = None

            continue  # done with level-1 handling

        # ------------------------------------------------------------
        # Level 2: DATE/PLAC inside an active event only
        # ------------------------------------------------------------
        if level == 2 and active_tag:
            if isinstance(current_record, Person):
                if active_tag == "BIRT":
                    if tag == "DATE":
                        current_record.birt_date = value
                    elif tag == "PLAC":
                        current_record.birt_place = value
                elif active_tag == "DEAT":
                    if tag == "DATE":
                        current_record.deat_date = value
                    elif tag == "PLAC":
                        current_record.deat_place = value

            elif isinstance(current_record, Family):
                if active_tag == "MARR":
                    if tag == "DATE":
                        current_record.marr_date = value
                    elif tag == "PLAC":
                        current_record.marr_place = value

            continue

        # For any other levels/tags, we ignore (sources/notes/etc)
        # This avoids contaminating core facts.

    # Post-processing: link family marriage date to spouses
    for fam in families.values():
        if fam.husb and fam.husb in individuals:
            individuals[fam.husb].marr_date = fam.marr_date
        if fam.wife and fam.wife in individuals:
            individuals[fam.wife].marr_date = fam.marr_date

    return individuals, families


def parse_gedcom(filename: str, show_progress: bool = True) -> Tuple[Dict[str, Person], Dict[str, Family]]:
    lines = _iter_lines_with_optional_progress(filename, show_progress=show_progress)
    return parse_gedcom_core(lines)
