#!/usr/bin/env python3
"""
reports/base.py
---------------
The report contract.

Every report in this application declares itself the same way and is invoked the
same way. There is no distinction anywhere -- in this file, in the registry, or
in the UI -- between reports that began life as Colab notebooks and reports that
were written for this app. A report is a report.

To add one: write a module exposing `REPORT = Report(...)` and list it in
`reports/registry.py`. It appears in the UI automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Optional

ParamKind = Literal["int", "year", "bool", "text", "choice"]


@dataclass
class Param:
    """A knob a report exposes to the UI."""
    key: str
    label: str
    kind: ParamKind = "int"
    default: Any = None
    help: str = ""
    choices: Optional[list] = None
    min: Optional[int] = None
    max: Optional[int] = None


# Parameters shared by many reports. Declared once so the UI can group them
# and so two reports never disagree about what "max generations" means.
P_MAX_GENS = Param("max_generations", "Max generations", "int", None,
                   "How far back to trace. Leave blank for the whole tree.", min=1, max=99)
P_YEAR_MIN = Param("year_min", "Earliest year", "year", None,
                   "Ignore events before this year. Blank for no limit.")
P_YEAR_MAX = Param("year_max", "Latest year", "year", None,
                   "Ignore events after this year. Blank for no limit.")


@dataclass
class RunSpec:
    """Everything a report needs to do its job."""
    gedcom_path: Path
    target_id: str
    target_name: str
    out_dir: Path                 # this report's own output folder
    data_dir: Path                # shared cache: location_library.json, overrides
    params: dict = field(default_factory=dict)
    pipeline: Any = None          # PipelineResult, when the report asked for it
    log: Callable[[str], None] = lambda m: None

    def p(self, key: str, default=None):
        v = self.params.get(key, default)
        return default if v in ("", None) else v


@dataclass
class Artifact:
    """One output file, plus how the results page should present it."""
    path: Path
    title: str
    kind: Literal["html", "csv", "pdf", "json"] = "html"
    primary: bool = False
    note: str = ""


@dataclass
class Report:
    id: str
    title: str
    description: str
    run: Callable[[RunSpec], list]
    params: list = field(default_factory=list)
    needs_master_csv: bool = False   # reads master_tree.csv (person-level)
    needs_events: bool = False       # reads events.csv (event-level)
    needs_target: bool = True        # is a focus person meaningful here?
    requires: list = field(default_factory=list)  # other report ids to run first
    group: str = "Reports"
    order: int = 100

    def param_defaults(self) -> dict:
        return {p.key: p.default for p in self.params}


def csv_artifact(path: Path, title: str, note: str = "") -> Artifact:
    return Artifact(path=path, title=title, kind="csv", note=note)


def html_artifact(path: Path, title: str, note: str = "", primary: bool = True) -> Artifact:
    return Artifact(path=path, title=title, kind="html", primary=primary, note=note)
