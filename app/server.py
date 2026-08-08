#!/usr/bin/env python3
"""
app/server.py
-------------
The local web application.

Runs on localhost only. Nothing leaves the machine except geocoding lookups for
places that are not already cached, and map tiles when you view the map.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import traceback
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "core"), str(ROOT / "reports")):
    if p not in sys.path:
        sys.path.insert(0, p)

from flask import Flask, jsonify, request, send_file, render_template, abort  # noqa: E402

from core.events import load_tree                       # noqa: E402
from core.ancestry import search_people, walk_ancestors  # noqa: E402
from core.pipeline import run_pipeline, load_address_overrides   # noqa: E402
from reports import registry                             # noqa: E402
from reports.base import RunSpec                         # noqa: E402

DATA_DIR = ROOT / "data"
RUNS_DIR = ROOT / "runs"
CONFIG_PATH = DATA_DIR / "config.json"
DEFAULT_TARGET_NAME = "William Cyril McHenry"
DEFAULT_TARGET_HINT = {"name": "William Cyril McHenry", "birth_year": 1988}

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["JSON_SORT_KEYS"] = False

_tree_cache: dict = {}
_jobs: dict = {}
_jobs_lock = threading.Lock()


# --------------------------------------------------------------- helpers
def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def get_tree(gedcom_path: str):
    """Parse once per file, keyed on path + mtime so edits are picked up."""
    p = Path(gedcom_path)
    if not p.exists():
        raise FileNotFoundError(gedcom_path)
    key = (str(p.resolve()), p.stat().st_mtime_ns)
    if _tree_cache.get("key") != key:
        _tree_cache["key"] = key
        _tree_cache["tree"] = load_tree(str(p))
    return _tree_cache["tree"]


def pick_default_target(tree) -> dict | None:
    """Best match for the configured default person, by name then birth year."""
    cfg = load_config()
    if cfg.get("default_target_id") and cfg["default_target_id"] in tree.individuals:
        ind = tree.individuals[cfg["default_target_id"]]
        b = ind.first("BIRT")
        return {"id": ind.id, "name": ind.name, "birth": b.date if b else "",
                "birth_place": b.place if b else ""}
    hits = search_people(tree, DEFAULT_TARGET_HINT["name"], limit=25)
    if not hits:
        return None
    want = DEFAULT_TARGET_HINT.get("birth_year")
    if want:
        for h in hits:
            if str(want) in (h.get("birth") or ""):
                return h
    return hits[0]


def artifact_payload(art, run_dir: Path) -> dict:
    try:
        rel = art.path.relative_to(run_dir)
    except Exception:
        rel = art.path.name
    size = art.path.stat().st_size if art.path.exists() else 0
    return {"title": art.title, "kind": art.kind, "primary": art.primary,
            "note": art.note, "rel": str(rel).replace(os.sep, "/"),
            "bytes": size, "exists": art.path.exists()}


# ------------------------------------------------------------------ views
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "POST":
        cfg = load_config()
        cfg.update(request.get_json(force=True) or {})
        save_config(cfg)
        return jsonify(cfg)
    return jsonify(load_config())


@app.route("/api/reports")
def api_reports():
    out = []
    for r in registry.ALL_REPORTS:
        out.append({
            "id": r.id, "title": r.title, "description": r.description,
            "needs_target": r.needs_target, "requires": r.requires,
            "params": [{"key": p.key, "label": p.label, "kind": p.kind,
                        "default": p.default, "help": p.help,
                        "choices": p.choices, "min": p.min, "max": p.max}
                       for p in r.params],
        })
    return jsonify(out)


@app.route("/api/browse")
def api_browse():
    """Directory listing so a GEDCOM can be picked without typing a path."""
    raw = request.args.get("path", "")
    base = Path(raw).expanduser() if raw else Path.home()
    if not base.exists():
        base = Path.home()
    if base.is_file():
        base = base.parent
    try:
        entries = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return jsonify({"error": "Permission denied", "path": str(base),
                        "parent": str(base.parent), "dirs": [], "files": []})
    dirs = [{"name": e.name, "path": str(e)} for e in entries
            if e.is_dir() and not e.name.startswith(".")]
    files = [{"name": e.name, "path": str(e), "bytes": e.stat().st_size}
             for e in entries if e.is_file() and e.suffix.lower() in (".ged", ".gedcom")]
    drives = []
    if os.name == "nt":
        import string
        drives = [f"{d}:\\" for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]
    return jsonify({"path": str(base), "parent": str(base.parent),
                    "dirs": dirs, "files": files, "drives": drives})


@app.route("/api/tree/summary")
def api_tree_summary():
    path = request.args.get("gedcom", "")
    try:
        tree = get_tree(path)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    default = pick_default_target(tree)
    return jsonify({"individuals": len(tree.individuals), "families": len(tree.families),
                    "default_target": default})


@app.route("/api/people")
def api_people():
    path, q = request.args.get("gedcom", ""), request.args.get("q", "")
    try:
        tree = get_tree(path)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(search_people(tree, q, limit=60))


@app.route("/api/preview")
def api_preview():
    """How many ancestors a given depth yields -- shown live in the UI."""
    path, tid = request.args.get("gedcom", ""), request.args.get("target", "")
    gens = request.args.get("max_generations", "")
    try:
        tree = get_tree(path)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    limit = int(gens) if str(gens).isdigit() and int(gens) > 0 else None
    anc = walk_ancestors(tree, tid, limit)
    deepest = max((a.generation for a in anc.values()), default=0)
    return jsonify({"ancestors": len(anc), "deepest": deepest})


@app.route("/api/run", methods=["POST"])
def api_run():
    body = request.get_json(force=True) or {}
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"id": job_id, "state": "queued", "lines": [],
                         "reports": [], "error": None, "run_dir": None,
                         "started": datetime.now().isoformat(timespec="seconds")}
    threading.Thread(target=_execute, args=(job_id, body), daemon=True).start()
    return jsonify({"job": job_id})


@app.route("/api/job/<job_id>")
def api_job(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        abort(404)
    return jsonify(job)


@app.route("/runs/<run_id>/<path:rel>")
def serve_run_file(run_id, rel):
    target = (RUNS_DIR / run_id / rel).resolve()
    if not str(target).startswith(str(RUNS_DIR.resolve())) or not target.exists():
        abort(404)
    return send_file(str(target))


# ------------------------------------------------------------- execution
def _execute(job_id: str, body: dict) -> None:
    def emit(msg: str) -> None:
        with _jobs_lock:
            _jobs[job_id]["lines"].append(msg)

    def setstate(**kw) -> None:
        with _jobs_lock:
            _jobs[job_id].update(kw)

    try:
        setstate(state="running")
        gedcom = Path(body["gedcom"]).expanduser()
        target_id = body.get("target_id") or ""
        target_name = body.get("target_name") or ""
        selection = body.get("reports") or []
        params = body.get("params") or {}
        use_network = bool(body.get("use_network", True))

        reports = registry.resolve_selection(selection)
        if not reports:
            raise ValueError("No reports selected.")
        auto = [r.id for r in reports if r.id not in selection]
        if auto:
            emit(f"Also running {', '.join(auto)} (required by your selection).")

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + job_id[:4]
        run_dir = RUNS_DIR / run_id
        (run_dir / "reports").mkdir(parents=True, exist_ok=True)
        setstate(run_dir=run_id)

        need_events, need_master = registry.needs_pipeline(reports)
        shared = params.get("_shared", {})
        max_gens = shared.get("max_generations")
        max_gens = int(max_gens) if str(max_gens).strip().isdigit() else None

        def progress(i, total, place):
            if i % 25 == 0 or i == total:
                emit(f"  geocoding {i}/{total}")

        emit("Starting run...")
        overrides = load_address_overrides(DATA_DIR / "address_override.csv")
        if overrides:
            emit(f"Loaded {len(overrides)} manual place correction(s).")
        result = run_pipeline(
            gedcom_path=gedcom, target_id=target_id, data_dir=DATA_DIR, out_dir=run_dir,
            max_generations=max_gens, use_network=use_network,
            address_overrides=overrides,
            log=emit, progress=progress if need_events else None,
            need_master=need_master,
        )
        if result.unresolved_places:
            emit(f"{len(result.unresolved_places)} place(s) could not be geocoded.")

        for rep in reports:
            emit(f"Running: {rep.title}")
            out_dir = run_dir / "reports" / rep.id
            out_dir.mkdir(parents=True, exist_ok=True)
            merged = dict(rep.param_defaults())
            merged.update(shared)
            merged.update(params.get(rep.id, {}))
            spec = RunSpec(gedcom_path=gedcom, target_id=target_id, target_name=target_name,
                           out_dir=out_dir, data_dir=DATA_DIR, params=merged,
                           pipeline=result, log=emit)
            try:
                arts = rep.run(spec) or []
                with _jobs_lock:
                    _jobs[job_id]["reports"].append({
                        "id": rep.id, "title": rep.title, "ok": True,
                        "artifacts": [artifact_payload(a, run_dir) for a in arts]})
                emit(f"  done: {rep.title}")
            except Exception as e:
                emit(f"  FAILED: {rep.title} -- {e}")
                with _jobs_lock:
                    _jobs[job_id]["reports"].append({
                        "id": rep.id, "title": rep.title, "ok": False,
                        "error": str(e), "trace": traceback.format_exc()[-1500:],
                        "artifacts": []})

        setstate(state="done")
        emit("Run complete.")
    except Exception as e:
        setstate(state="error", error=f"{e}\n{traceback.format_exc()[-1200:]}")


def main():
    host = os.environ.get("GW_HOST", "127.0.0.1")
    port = int(os.environ.get("GW_PORT", "5333"))
    RUNS_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    url = f"http://{host}:{port}/"
    if os.environ.get("GW_OPEN", "1") == "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"\n  Genealogy Workbench running at {url}\n  Press Ctrl+C to stop.\n")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
