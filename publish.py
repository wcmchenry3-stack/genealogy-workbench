#!/usr/bin/env python3
"""
publish.py
----------
Publishes a subset of a finished run's report artifacts to
genealogy_reports_site (a sibling repo, private, hosted behind Cloudflare
Access) so they're viewable from anywhere, not just this machine.

Best-effort by design: a publish failure (missing sibling repo, git error,
network hiccup on push) is logged and swallowed, never raised -- publishing
is a nice-to-have on top of a successful local run, not a requirement for
one. genealogy_reports_site has no write path of its own; this is the only
thing that ever pushes to it.

Note: this pushes directly to genealogy_reports_site's main branch rather
than going through a PR -- the same deliberate exception
scripts/house_2026_races/publish.py documents. That branch only ever
receives generated HTML from this script, never hand-edited source needing
review.

Only a fixed subset of reports is published (see PUBLISHED_REPORTS below):
Ancestor Timelines, Locations, Ancestor Chart, and the *classic* offline
research map. The interactive worldwide map (r_map.py) is deliberately
excluded -- it pulls Leaflet from a CDN and OpenStreetMap tiles over the
network, which the hub's CSP does not currently allow.

Each publish is a plain overwrite of site/genealogy/, not a versioned
append -- there's no need to track a history of the family tree the way
house_2026_races tracks election-result trends. A prior version is still
recoverable from genealogy_reports_site's git history unless it's
explicitly rewritten; if a person's data needs to be fully removed rather
than just corrected, an overwrite-and-push here is not sufficient on its
own.

Usage:
    python publish.py              # publishes the most recent run
    python publish.py <run_id>     # publishes a specific run (runs/<run_id>)
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNS_DIR = ROOT / "runs"
REPORTS_SITE_DIR = ROOT.parent / "genealogy_reports_site"
_GIT_TIMEOUT_SECONDS = 30

# (report id in reports/registry.py, artifact filename inside
#  runs/<run_id>/reports/<id>/, publish subfolder under site/genealogy/,
#  card title, card description)
PUBLISHED_REPORTS = [
    ("timelines", "timelines.html", "timelines", "Ancestor Timelines",
     "Every ancestor with their locations in date order, on a shared time axis."),
    ("locations", "locations.html", "locations", "Locations",
     "Events organised by place — one card per town, ranked for research."),
    ("tree", "ancestor_chart.html", "chart", "Ancestor Chart",
     "Printable pedigree chart, four generations per page."),
    ("map_classic", "map_classic.html", "map", "Research Map",
     "Offline SVG research map of every located ancestral event."),
]

_CARD_PAGE_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Family Tree Reports</title>
<style>
  :root {{
    --bg: #ffffff; --fg: #1a1a2e; --muted: #6b7280; --border: #e5e7eb;
    --panel: #f9fafb; --accent: #4338ca;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #0f1117; --fg: #e5e7eb; --muted: #9ca3af; --border: #2a2e3a; --panel: #171a23;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--fg); margin: 0; padding: 24px;
    font: 14px/1.5 -apple-system, Segoe UI, Roboto, sans-serif;
  }}
  .page {{ max-width: 640px; margin: 40px auto; }}
  a.back {{ color: var(--muted); font-size: 0.85rem; text-decoration: none; }}
  a.back:hover {{ color: var(--accent); }}
  h1 {{ font-size: 1.6rem; margin: 14px 0 6px; }}
  .subtitle {{ color: var(--muted); font-size: 0.9rem; margin-bottom: 32px; }}
  .card {{
    display: block; background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 18px 20px; margin-bottom: 12px;
    text-decoration: none; color: inherit; transition: border-color 0.15s;
  }}
  .card:hover {{ border-color: var(--accent); }}
  .card .name {{ font-size: 1.05rem; font-weight: 600; margin-bottom: 4px; }}
  .card .desc {{ color: var(--muted); font-size: 0.85rem; }}
  @media (max-width: 480px) {{
    body {{ padding: 16px; }}
    .page {{ margin: 20px auto; }}
  }}
</style>
</head>
<body>
<div class="page">
  <a class="back" href="/">&larr; Reports</a>
  <h1>Family Tree Reports</h1>
  <div class="subtitle">{subtitle}</div>
{cards}
</div>
</body>
</html>
"""


def _latest_run_id() -> str | None:
    if not RUNS_DIR.is_dir():
        return None
    runs = sorted((p.name for p in RUNS_DIR.iterdir() if p.is_dir()), reverse=True)
    return runs[0] if runs else None


def _run_context(run_id: str) -> dict:
    ctx_path = RUNS_DIR / run_id / "context.json"
    if not ctx_path.is_file():
        return {}
    try:
        return json.loads(ctx_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _card_page(cards: list[dict], focus_name: str | None, published_at: str) -> str:
    subtitle = f"Centred on {focus_name} &middot; published {published_at}" if focus_name else f"Published {published_at}"
    card_html = "\n".join(
        f'  <a class="card" href="/genealogy/{c["subpath"]}/">\n'
        f'    <div class="name">{c["title"]}</div>\n'
        f'    <div class="desc">{c["desc"]}</div>\n'
        f'  </a>'
        for c in cards
    )
    return _CARD_PAGE_TEMPLATE.format(subtitle=subtitle, cards=card_html)


def publish_run(run_id: str, logger: logging.Logger, reports_site_dir: Path = REPORTS_SITE_DIR) -> bool:
    """Copy the published subset of `run_id`'s report artifacts into
    genealogy_reports_site/site/genealogy/, regenerate the landing card
    page, commit, and push. Returns True if publishing succeeded (or there
    was nothing new to publish), False if it was skipped or failed --
    never raises."""
    site_dir = reports_site_dir.resolve()
    if not (site_dir / ".git").is_dir():
        logger.warning(f"Skipping publish: {site_dir} is not a git repo (genealogy_reports_site not found)")
        return False

    run_dir = RUNS_DIR / run_id
    genealogy_dir = site_dir / "site" / "genealogy"
    cards: list[dict] = []
    for report_id, filename, subpath, title, desc in PUBLISHED_REPORTS:
        src = run_dir / "reports" / report_id / filename
        if not src.is_file():
            logger.warning(f"Skipping {title}: no artifact at {src} (report not selected for this run?)")
            continue
        dest_dir = genealogy_dir / subpath
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(src, dest_dir / "index.html")
        except OSError as exc:
            logger.error(f"Publish failed: could not copy {src} to {dest_dir}: {exc}")
            return False
        cards.append({"subpath": subpath, "title": title, "desc": desc})

    if not cards:
        logger.error(f"Publish failed: none of the {len(PUBLISHED_REPORTS)} publishable reports were found in run {run_id}")
        return False

    ctx = _run_context(run_id)
    published_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    (genealogy_dir / "index.html").write_text(
        _card_page(cards, ctx.get("focus_person_name"), published_at), encoding="utf-8"
    )

    def _run(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(args, cwd=site_dir, capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS)

    try:
        status = _run(["git", "status", "--porcelain", "--", "site/genealogy"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.error(f"Publish failed: could not run git in {site_dir}: {exc}")
        return False
    if status.returncode != 0:
        logger.error(f"Publish failed: git status error: {status.stderr.strip()}")
        return False
    if not status.stdout.strip():
        logger.info("Publish skipped: reports unchanged since last publish")
        return True

    add = _run(["git", "add", "site/genealogy"])
    if add.returncode != 0:
        logger.error(f"Publish failed: git add error: {add.stderr.strip()}")
        return False

    commit = _run(["git", "commit", "-m", f"Publish genealogy reports (run {run_id})"])
    if commit.returncode != 0:
        logger.error(f"Publish failed: git commit error: {commit.stderr.strip()}")
        return False

    # "origin HEAD" (not a bare "push") pushes the current branch to its
    # same-named remote branch regardless of local branch naming/upstream
    # tracking config -- avoids relying on push.default behavior matching
    # whatever this machine happens to have configured.
    push = _run(["git", "push", "origin", "HEAD"])
    if push.returncode != 0:
        logger.error(f"Publish failed: git push error: {push.stderr.strip()}")
        return False

    logger.info(f"Published {len(cards)} report(s) to genealogy_reports_site — Render will redeploy shortly")
    return True


def _cli_logger() -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    return logging.getLogger("publish")


if __name__ == "__main__":
    cli_logger = _cli_logger()
    target_run_id = sys.argv[1] if len(sys.argv) > 1 else _latest_run_id()
    if not target_run_id:
        cli_logger.error("No run_id given and no runs/ found. Run a report first, or pass a run_id explicitly.")
        sys.exit(1)
    success = publish_run(target_run_id, cli_logger)
    sys.exit(0 if success else 1)
