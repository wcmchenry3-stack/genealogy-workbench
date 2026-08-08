#!/usr/bin/env python
# coding: utf-8
from __future__ import annotations

# In[ ]:


#!/usr/bin/env python3
# coding: utf-8
"""
run_context.py
--------------
Milestone 2:
- Run folder is timestamp-based, not focus-person-based
- All report outputs go into runs/{run_id}/reports/{report_name}/...
- Convenience helpers for report directories/paths
"""


import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass
class RunContext:
    run_id: str
    run_dir: Path
    reports_dir: Path
    log_path: Path
    context_path: Path

    # Optional runtime fields (may be None)
    focus_person_name: Optional[str] = None
    root_id: Optional[str] = None
    max_gens: Optional[int] = None

    started_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Convert Paths to strings for JSON
        for k in ("run_dir", "reports_dir", "log_path", "context_path"):
            d[k] = str(d[k])
        return d

    def save_context_json(self):
        payload = self.to_dict()
        self.context_path.parent.mkdir(parents=True, exist_ok=True)
        with self.context_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    # ---- Milestone 2 helpers ----

    def report_dir(self, report_name: str) -> Path:
        """Return runs/{run_id}/reports/{report_name}/ and ensure it exists."""
        p = self.reports_dir / report_name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def report_path(self, report_name: str, filename: str) -> Path:
        """Return full path for a report file inside its report directory."""
        return self.report_dir(report_name) / filename


def new_run_id() -> str:
    # Folder-safe timestamp (no colons)
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def create_run_context(base_dir: Path) -> RunContext:
    """
    Create a new run folder structure under: {base_dir}/runs/{run_id}/
    """
    rid = new_run_id()
    run_dir = base_dir / "runs" / rid
    reports_dir = run_dir / "reports"
    log_path = run_dir / "run.log"
    context_path = run_dir / "context.json"

    run_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    ctx = RunContext(
        run_id=rid,
        run_dir=run_dir,
        reports_dir=reports_dir,
        log_path=log_path,
        context_path=context_path,
        started_at=datetime.now().isoformat(timespec="seconds"),
    )
    ctx.save_context_json()
    return ctx
