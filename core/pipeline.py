#!/usr/bin/env python3
"""
core/pipeline.py
----------------
One pass over a GEDCOM produces both shared data files.

  master_tree.csv  -- the person-level contract, 21 columns, written by the
                      existing `gedcom_cleaner.process_gedcom_to_csv` exactly as
                      it always has. The tree, diagnostics, duplicates,
                      immigrant and spouse reports read this and are untouched.

  events.csv       -- the event-level companion. One row per person per dated
                      place, with the place resolved and geocoded. The timeline,
                      location and map reports read this.

The cleaner is used verbatim. It does `from gedcom_geocoder import get_coords`,
which binds the name at import time, so the faster three-tier geocoder is
injected by setting the attribute on the cleaner module afterwards. No line of
their logic changes; it just gets a better geocoder underneath.
"""
from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

CORE_DIR = Path(__file__).resolve().parent
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))          # ported modules use flat imports

from .events import load_tree, Tree                     # noqa: E402
from .ancestry import walk_ancestors, Ancestor          # noqa: E402
from .geocode import Geocoder, LocationCache            # noqa: E402
from .places import parse_place                         # noqa: E402

# ------------------------------------------------------ cemetery enrichment
CEM_NAME = re.compile(
    r"([A-Z][A-Za-z'\.\-]*(?:\s+[A-Z][A-Za-z'\.\-]*){0,4}\s+"
    r"(?:Cemetery|Cemeteries|Memorial Gardens|Memorial Park|Burial Ground|"
    r"Churchyard|Graveyard|Mausoleum))")
CEM_ADDR = re.compile(r"\b(\d{2,6}\s+[A-Z][A-Za-z\.\-]*(?:\s+[A-Z][A-Za-z\.\-]*){0,3}"
                      r"\s+(?:Road|Rd|Street|St|Avenue|Ave|Drive|Dr|Highway|Hwy|Pike|Lane|Ln|Blvd|Boulevard))\b")
CEM_PLOT = re.compile(r"\b((?:Section|Sec|Lot|Block|Grave|Plot|Row|Tier)\.?\s*[A-Z0-9\-]+"
                      r"(?:\s*,?\s*(?:Section|Sec|Lot|Block|Grave|Plot|Row|Tier)\.?\s*[A-Z0-9\-]+)*)\b", re.I)
_CEM_REJECT = re.compile(r"^(U\.?S\.?|Find A Grave|Web|Index|Ohio|Michigan|National)\b", re.I)


def mine_cemetery(event, person_notes: list[str]) -> tuple:
    """Recover cemetery name / address / plot from citation text around a burial."""
    blobs = list(event.citations) + list(person_notes)
    name = addr = plot = None
    for b in blobs:
        if not name:
            m = CEM_NAME.search(b)
            if m and not _CEM_REJECT.match(m.group(1).strip()):
                name = m.group(1).strip()
        if not plot:
            m = CEM_PLOT.search(b)
            if m:
                plot = m.group(1).strip()
        if not addr:
            m = CEM_ADDR.search(b)
            if m:
                addr = m.group(1).strip()
    return name, addr, plot


def load_address_overrides(csv_path: Path) -> dict:
    """Read manual place corrections, tolerating both column layouts seen in the wild.

    The original loader expects `original_place, clean_address, lat, lon`, but the
    exported override file actually carries `Name, Value.lat, Value.lon,
    Value.address`. Under the old loader every row silently produced an empty key
    and was dropped, so the corrections were never applied to anything. Accepting
    both spellings here fixes that without editing the cleaner, which takes this
    dictionary as a parameter.
    """
    import csv as _csv
    aliases = {
        "place": ("original_place", "name", "place", "original", "raw"),
        "address": ("clean_address", "value.address", "address", "clean"),
        "lat": ("lat", "value.lat", "latitude"),
        "lon": ("lon", "value.lon", "longitude", "lng"),
    }
    out: dict = {}
    p = Path(csv_path)
    if not p.exists():
        return out
    with open(p, newline="", encoding="utf-8-sig") as fh:
        reader = _csv.DictReader(fh)
        cols = {(c or "").strip().lower(): c for c in (reader.fieldnames or [])}

        def pick(row, which):
            for a in aliases[which]:
                if a in cols:
                    v = row.get(cols[a])
                    if v not in (None, ""):
                        return str(v).strip()
            return ""

        for row in reader:
            key = pick(row, "place").lower()
            if not key:
                continue
            out[key] = {"address": pick(row, "address"),
                        "lat": pick(row, "lat"), "lon": pick(row, "lon")}
    return out


EVENT_COLUMNS = [
    "PersonID", "PersonName", "Sex", "Generation", "Relationship", "Line",
    "Event", "Tag", "Date", "Year", "DateQualifier",
    "PlaceRaw", "Locality", "Subregion", "Region", "RegionCode",
    "Country", "CountryCode", "PlaceKey", "PlaceLabel",
    "Lat", "Lon", "GeoPrecision", "GeoSource",
    "Cemetery", "CemeteryAddress", "CemeteryPlot",
]


@dataclass
class PipelineResult:
    master_csv: Path
    events_csv: Path
    tree: Tree
    ancestors: dict
    event_rows: list
    geo_stats: dict
    unresolved_places: list


def build_master_csv(*, gedcom_path: Path, master_csv: Path, geocoder: Geocoder,
                     address_overrides: Optional[dict] = None,
                     log: Optional[Callable[[str], None]] = None) -> Path:
    """Run the existing cleaner, with the three-tier geocoder injected."""
    import gedcom_cleaner  # flat import, straight from core/

    def _get_coords(location_name, progress_cb=None):
        if not location_name:
            return None
        _ref, res = geocoder.resolve(location_name)
        if not res.ok:
            return None
        return {"lat": res.lat, "lon": res.lon, "address": res.display or location_name}

    def _save_library():
        geocoder.cache.save()

    gedcom_cleaner.get_coords = _get_coords        # names were bound at import
    gedcom_cleaner.save_library = _save_library

    master_csv.parent.mkdir(parents=True, exist_ok=True)
    if log:
        log("Building master_tree.csv (person-level contract)...")
    gedcom_cleaner.process_gedcom_to_csv(
        gedcom_path=str(gedcom_path),
        output_csv_path=str(master_csv),
        address_overrides=address_overrides or {},
    )
    return master_csv


def build_events_csv(*, tree: Tree, ancestors: dict, events_csv: Path, geocoder: Geocoder,
                     log: Optional[Callable[[str], None]] = None,
                     progress: Optional[Callable[[int, int, str], None]] = None):
    """Emit the event-level companion for the ancestors in scope."""
    placed = []
    for pid, anc in ancestors.items():
        ind = tree.individuals.get(pid)
        if not ind:
            continue
        for ev in ind.events:
            if ev.place:
                placed.append((anc, ind, ev))

    distinct = list(dict.fromkeys(ev.place for _a, _i, ev in placed))
    if log:
        log(f"Resolving {len(distinct)} distinct places across {len(placed)} events...")
    resolved = geocoder.resolve_many(distinct, progress=progress)

    rows, unresolved = [], []
    for anc, ind, ev in placed:
        ref, geo = resolved.get(ev.place, (None, None))
        if ref is None:
            ref = parse_place(ev.place, geocoder.counties)
        cem = cem_addr = cem_plot = None
        if ev.tag == "BURI":
            cem, cem_addr, cem_plot = mine_cemetery(ev, ind.notes)
            cem = cem or (ref.cemetery if ref else None)
        if geo is None or not geo.ok:
            unresolved.append(ev.place)
        rows.append({
            "PersonID": ind.id, "PersonName": ind.name, "Sex": ind.sex,
            "Generation": anc.generation, "Relationship": anc.relationship, "Line": anc.line,
            "Event": ev.type, "Tag": ev.tag, "Date": ev.date, "Year": ev.year or "",
            "DateQualifier": ev.qualifier,
            "PlaceRaw": ev.place,
            "Locality": (ref.locality if ref else "") or "",
            "Subregion": (ref.subregion if ref else "") or "",
            "Region": (ref.region if ref else "") or "",
            "RegionCode": (ref.region_code if ref else "") or "",
            "Country": (ref.country if ref else "") or "",
            "CountryCode": (ref.country_code if ref else "") or "",
            "PlaceKey": "|".join(str(x) for x in ref.key()) if ref else "",
            "PlaceLabel": ref.label() if ref else ev.place,
            "Lat": geo.lat if geo and geo.ok else "",
            "Lon": geo.lon if geo and geo.ok else "",
            "GeoPrecision": geo.precision if geo else "none",
            "GeoSource": geo.source if geo else "none",
            "Cemetery": cem or "", "CemeteryAddress": cem_addr or "", "CemeteryPlot": cem_plot or "",
            "_sort": ev.sort or 0,
        })

    rows.sort(key=lambda r: (r["Generation"], r["PersonName"], r["_sort"]))
    for r in rows:
        r.pop("_sort", None)

    events_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(events_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=EVENT_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return rows, sorted(set(unresolved))


def run_pipeline(*, gedcom_path: Path, target_id: str, data_dir: Path, out_dir: Path,
                 max_generations: Optional[int] = None, use_network: bool = True,
                 address_overrides: Optional[dict] = None,
                 log: Optional[Callable[[str], None]] = None,
                 progress: Optional[Callable[[int, int, str], None]] = None,
                 need_master: bool = True) -> PipelineResult:
    log = log or (lambda m: None)
    gedcom_path, data_dir, out_dir = Path(gedcom_path), Path(data_dir), Path(out_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    cache = LocationCache(data_dir / "location_library.json")
    geocoder = Geocoder(cache=cache, use_network=use_network)

    log("Reading GEDCOM...")
    tree = load_tree(str(gedcom_path))
    log(f"  {len(tree.individuals)} people, {len(tree.families)} families")

    ancestors = walk_ancestors(tree, target_id, max_generations)
    deepest = max((a.generation for a in ancestors.values()), default=0)
    log(f"Traced {len(ancestors)} ancestors across {deepest} generations")

    events_csv = out_dir / "events.csv"
    rows, unresolved = build_events_csv(tree=tree, ancestors=ancestors, events_csv=events_csv,
                                        geocoder=geocoder, log=log, progress=progress)
    log(f"  {len(rows)} placed events -> {events_csv.name}")

    master_csv = data_dir / "master_tree.csv"
    if need_master:
        build_master_csv(gedcom_path=gedcom_path, master_csv=master_csv, geocoder=geocoder,
                         address_overrides=address_overrides, log=log)
    cache.save()
    log(f"Geocoding: {geocoder.stats}")

    return PipelineResult(master_csv=master_csv, events_csv=events_csv, tree=tree,
                          ancestors=ancestors, event_rows=rows,
                          geo_stats=dict(geocoder.stats), unresolved_places=unresolved)
