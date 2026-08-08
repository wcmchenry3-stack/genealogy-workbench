#!/usr/bin/env python3
"""
core/ancestry.py
----------------
The universal ancestor walk.

The earlier version of this pruned lines geographically -- it stopped climbing
whenever an ancestor was neither born nor died in a target state. That baked
one report's filter into the data itself, which is why it could not go
worldwide.

Here the walk is unconditional: every parent line, every country, bounded only
by a generation limit. Filtering (by year, by region, by anything) is the
reports' business, applied to the full result. Collect everything once; let
each view decide what it wants to show.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from .events import Tree


@dataclass
class Ancestor:
    id: str
    name: str
    sex: str
    generation: int
    path: list[str] = field(default_factory=list)   # ["father", "mother", ...]
    via: list[str] = field(default_factory=list)     # ids from target up to here

    @property
    def relationship(self) -> str:
        """'father', 'grandmother', 'great-great-grandfather', '12x great-grandfather'.

        Spelling out "great-" thirty times is unreadable, so past three the
        count is written as a multiplier instead.
        """
        if self.generation == 0:
            return "self"
        base = self.path[-1]
        g = len(self.path)
        if g == 1:
            return base
        if g == 2:
            return "grand" + base
        greats = g - 2
        if greats <= 3:
            return "great-" * greats + "grand" + base
        return f"{greats}x great-grand{base}"

    @property
    def line(self) -> str:
        """Which side of the family: paternal or maternal, by the first step."""
        if self.generation == 0:
            return "self"
        return "paternal" if self.path[0] == "father" else "maternal"


def walk_ancestors(tree: Tree, root_id: str, max_generations: Optional[int] = None
                   ) -> dict[str, Ancestor]:
    """Breadth-first up every parent line from `root_id`.

    max_generations=None (or 0) means no limit. Cycles -- which do occur in real
    trees through data errors or cousin marriages -- are visited once and not
    re-expanded, so the walk always terminates.
    """
    out: dict[str, Ancestor] = {}
    if root_id not in tree.individuals:
        return out

    limit = max_generations if (max_generations and max_generations > 0) else None
    root = tree.individuals[root_id]
    out[root_id] = Ancestor(id=root_id, name=root.name, sex=root.sex, generation=0)

    q: deque = deque([(root_id, 0, [], [root_id])])
    while q:
        pid, gen, path, via = q.popleft()
        if limit is not None and gen >= limit:
            continue
        for parent_id in tree.parents_of(pid):
            if parent_id in out or parent_id not in tree.individuals:
                continue
            p = tree.individuals[parent_id]
            step = "father" if (p.sex or "").upper().startswith("M") else "mother"
            anc = Ancestor(id=parent_id, name=p.name, sex=p.sex, generation=gen + 1,
                           path=path + [step], via=via + [parent_id])
            out[parent_id] = anc
            q.append((parent_id, gen + 1, anc.path, anc.via))
    return out


def walk_descendants(tree: Tree, root_id: str, max_generations: Optional[int] = None
                     ) -> dict[str, Ancestor]:
    """Same shape, downward. Used by reports that want a whole family branch."""
    out: dict[str, Ancestor] = {}
    if root_id not in tree.individuals:
        return out
    limit = max_generations if (max_generations and max_generations > 0) else None
    root = tree.individuals[root_id]
    out[root_id] = Ancestor(id=root_id, name=root.name, sex=root.sex, generation=0)
    q: deque = deque([(root_id, 0)])
    while q:
        pid, gen = q.popleft()
        if limit is not None and gen >= limit:
            continue
        for kid in tree.children_of(pid):
            if kid in out or kid not in tree.individuals:
                continue
            c = tree.individuals[kid]
            out[kid] = Ancestor(id=kid, name=c.name, sex=c.sex, generation=gen + 1)
            q.append((kid, gen + 1))
    return out


def search_people(tree: Tree, query: str, limit: int = 40) -> list[dict]:
    """Free-text person search for the target picker in the UI."""
    q = (query or "").strip().lower()
    hits = []
    for ind in tree.individuals.values():
        name = ind.name or ""
        if q and q not in name.lower():
            continue
        b, d = ind.first("BIRT"), ind.first("DEAT")
        hits.append({
            "id": ind.id, "name": name, "sex": ind.sex,
            "birth": (b.date if b else ""), "birth_place": (b.place if b else ""),
            "death": (d.date if d else ""), "death_place": (d.place if d else ""),
            "_y": (b.year if b and b.year else 9999),
        })
    hits.sort(key=lambda h: (h["_y"], h["name"]))
    for h in hits:
        h.pop("_y", None)
    return hits[:limit]
