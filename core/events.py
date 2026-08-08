#!/usr/bin/env python3
"""
core/events.py
--------------
The event-level view of a GEDCOM.

`gedcom_parser.py` gives the *person-level* view -- one row per person with
birth, death and marriage -- which is exactly what `master_tree.csv` needs and
what the tree, diagnostics, duplicates, immigrant and spouse reports consume.
That contract is deliberately left alone.

This module gives the complementary *event-level* view: one record per person
per dated place, including residence, census, burial, probate and military.
Those events are where somebody actually lived, and the timeline, location and
map reports are built on them. Same source file, different shape -- not a
second copy of the same thing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

LINE_RE = re.compile(r"^(\d+)\s+(@[^@]+@)?\s*(_?[A-Za-z0-9]+)\s*(.*)$")

EVENT_TAGS = {
    "BIRT": "Birth", "DEAT": "Death", "BURI": "Burial", "RESI": "Residence",
    "CENS": "Census", "MARR": "Marriage", "BAPM": "Baptism", "CHR": "Christening",
    "PROB": "Probate", "OCCU": "Occupation", "_MILT": "Military", "IMMI": "Immigration",
    "NATU": "Naturalization", "EMIG": "Emigration", "EVEN": "Event",
}
# Events that place a person somewhere at a moment in time.
PLACED_EVENTS = set(EVENT_TAGS) - {"OCCU"}

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_QUAL = re.compile(r"^(ABT|ABOUT|EST|CAL|BEF|BEFORE|AFT|AFTER|FROM|BET|CIRCA|C)\b\.?\s*(.*)$", re.I)


def parse_date(s: str):
    """-> (year, sortkey, display, qualifier). Year is None when undated."""
    if not s:
        return None, 0, "", ""
    raw, qual = s.strip(), ""
    m = DATE_QUAL.match(raw)
    if m:
        qual, raw = m.group(1).lower(), m.group(2)
    years = re.findall(r"\b(1[0-9]{3}|20[0-9]{2})\b", raw)
    if not years:
        return None, 0, s.strip(), qual
    y = int(years[0])
    mo = dy = 0
    mm = re.search(r"\b([A-Za-z]{3,9})\b", raw)
    if mm and mm.group(1)[:3].lower() in MONTHS:
        mo = MONTHS[mm.group(1)[:3].lower()]
    dd = re.match(r"^\s*(\d{1,2})\b", raw)
    if dd and int(dd.group(1)) <= 31:
        dy = int(dd.group(1))
    return y, y * 10000 + mo * 100 + dy, s.strip(), qual


@dataclass
class Event:
    tag: str
    type: str
    date: str = ""
    year: Optional[int] = None
    sort: int = 0
    qualifier: str = ""
    place: str = ""
    citations: list[str] = field(default_factory=list)


@dataclass
class Individual:
    id: str
    name: str = "(unknown)"
    sex: str = ""
    famc: list[str] = field(default_factory=list)
    fams: list[str] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def first(self, tag: str) -> Optional[Event]:
        return next((e for e in self.events if e.tag == tag), None)


@dataclass
class FamilyRec:
    id: str
    husb: Optional[str] = None
    wife: Optional[str] = None
    children: list[str] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)


@dataclass
class Tree:
    individuals: dict[str, Individual] = field(default_factory=dict)
    families: dict[str, FamilyRec] = field(default_factory=dict)

    def parents_of(self, pid: str) -> list[str]:
        out = []
        ind = self.individuals.get(pid)
        if not ind:
            return out
        for fid in ind.famc:
            fam = self.families.get(fid)
            if fam:
                out += [p for p in (fam.husb, fam.wife) if p]
        return out

    def children_of(self, pid: str) -> list[str]:
        out = []
        ind = self.individuals.get(pid)
        if not ind:
            return out
        for fid in ind.fams:
            fam = self.families.get(fid)
            if fam:
                out += fam.children
        return out


def load_tree(path: str) -> Tree:
    """Read a GEDCOM into the event-level model."""
    tree = Tree()
    cur = None          # Individual | FamilyRec | None
    cur_ev: Optional[Event] = None
    prev_val_ref = None  # for CONC/CONT folding

    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        for raw in fh:
            m = LINE_RE.match(raw.rstrip("\r\n"))
            if not m:
                continue
            lvl, xref, tag, val = int(m.group(1)), m.group(2), m.group(3), (m.group(4) or "").strip()

            if lvl == 0:
                cur_ev = None
                prev_val_ref = None
                if tag == "INDI" and xref:
                    cur = tree.individuals.setdefault(xref, Individual(id=xref))
                elif tag == "FAM" and xref:
                    cur = tree.families.setdefault(xref, FamilyRec(id=xref))
                else:
                    cur = None
                continue
            if cur is None:
                continue

            # continuation lines extend whatever value came before
            if tag in ("CONC", "CONT") and prev_val_ref is not None:
                lst, idx = prev_val_ref
                lst[idx] += ("" if tag == "CONC" else " ") + val
                continue

            if lvl == 1:
                cur_ev = None
                if isinstance(cur, Individual):
                    if tag == "NAME" and cur.name == "(unknown)":
                        cur.name = re.sub(r"\s+", " ", val.replace("/", "")).strip() or "(unknown)"
                    elif tag == "SEX":
                        cur.sex = val
                    elif tag == "FAMC":
                        cur.famc.append(val)
                    elif tag == "FAMS":
                        cur.fams.append(val)
                    elif tag == "NOTE" and val:
                        cur.notes.append(val)
                        prev_val_ref = (cur.notes, len(cur.notes) - 1)
                    elif tag in EVENT_TAGS:
                        cur_ev = Event(tag=tag, type=EVENT_TAGS[tag])
                        cur.events.append(cur_ev)
                        if val and tag in ("BIRT", "DEAT"):
                            cur_ev.date = val
                else:  # FamilyRec
                    if tag == "HUSB":
                        cur.husb = val
                    elif tag == "WIFE":
                        cur.wife = val
                    elif tag == "CHIL":
                        cur.children.append(val)
                    elif tag in EVENT_TAGS:
                        cur_ev = Event(tag=tag, type=EVENT_TAGS[tag])
                        cur.events.append(cur_ev)
                continue

            if cur_ev is not None and lvl >= 2:
                if lvl == 2 and tag == "DATE":
                    cur_ev.date = val
                elif lvl == 2 and tag == "PLAC":
                    cur_ev.place = val
                elif tag in ("NOTE", "PAGE", "TEXT", "TITL") and val:
                    cur_ev.citations.append(val)
                    prev_val_ref = (cur_ev.citations, len(cur_ev.citations) - 1)

    # resolve dates once, up front
    for ind in tree.individuals.values():
        for e in ind.events:
            e.year, e.sort, _, e.qualifier = parse_date(e.date)
    for fam in tree.families.values():
        for e in fam.events:
            e.year, e.sort, _, e.qualifier = parse_date(e.date)

    # a marriage belongs to both spouses' timelines
    for fam in tree.families.values():
        for e in fam.events:
            if e.tag != "MARR" or not (e.place or e.date):
                continue
            for pid in (fam.husb, fam.wife):
                ind = tree.individuals.get(pid or "")
                if ind and not any(x.tag == "MARR" and x.date == e.date for x in ind.events):
                    ind.events.append(Event(tag=e.tag, type=e.type, date=e.date, year=e.year,
                                            sort=e.sort, qualifier=e.qualifier, place=e.place))

    for ind in tree.individuals.values():
        ind.events.sort(key=lambda e: (e.sort or 0))
    return tree
