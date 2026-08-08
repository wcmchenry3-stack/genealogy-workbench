#!/usr/bin/env python
# coding: utf-8
from __future__ import annotations

# In[ ]:


#!/usr/bin/env python3
# coding: utf-8
"""
run_logger.py
-------------
Simple per-run logger:
- Writes to a single txt log file (append-only)
- Optionally echoes to console (useful in Colab)
"""


import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class RunLogger:
    log_path: Path
    echo: bool = True  # also print to console

    def _ts(self) -> str:
        # ISO-ish timestamp, readable in logs
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _write(self, level: str, msg: str):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        line = f"[{self._ts()}] {level:<5} {msg}\n"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line)
        if self.echo:
            print(line, end="")

    def info(self, msg: str):
        self._write("INFO", msg)

    def warn(self, msg: str):
        self._write("WARN", msg)

    def error(self, msg: str):
        self._write("ERROR", msg)

    def exception(self, msg: str):
        """
        Log a message plus the current exception traceback.
        Call inside an except block.
        """
        tb = traceback.format_exc()
        self._write("ERROR", msg)
        # Keep traceback readable in txt logs
        for line in tb.rstrip().splitlines():
            self._write("ERROR", line)
