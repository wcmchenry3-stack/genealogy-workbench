#!/usr/bin/env python3
"""
core/geocode.py
---------------
Turning place text into coordinates, in three tiers.

  1. location_library.json  -- the cache. Instant. Grows with every run and is
     shared with the existing pipeline, so past lookups are never repeated.
  2. offline US gazetteer   -- instant, no network, covers the ~60% of distinct
     places in a typical US-rooted tree. Town-centre accuracy, reported as such.
  3. Nominatim (OpenStreetMap) -- worldwide, authoritative, but rate-limited to
     roughly one request per second by their usage policy, so it goes last.

Every tier writes its answer back to the cache, including confirmed failures,
so a place is never looked up twice. Precision is always reported honestly --
a pin placed at a county centroid says so rather than implying a street match.
"""
from __future__ import annotations

import collections
import json
import re
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .places import COUNTY_SUFFIX, PlaceRef, _subregion_name, parse_place, counties_index_from_zipcodes

NOMINATIM_UA = "genealogy-workbench/1.0 (wcmchenry3@gmail.com)"
MIN_DELAY_S = 1.1          # Nominatim asks for <= 1 req/sec; leave headroom.


@dataclass
class GeoResult:
    lat: Optional[float] = None
    lon: Optional[float] = None
    precision: str = "none"     # city | county | country | nominatim:<type> | none
    source: str = "none"        # cache | offline | nominatim | none
    display: str = ""

    @property
    def ok(self) -> bool:
        return self.lat is not None and self.lon is not None


# ----------------------------------------------------------------- cache
class LocationCache:
    """Reads and writes the same location_library.json the Colab pipeline used."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict = {}
        self._dirty = False
        self._lock = threading.Lock()
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8")) or {}
            except Exception:
                self.data = {}

    def get(self, key: str):
        return self.data.get(key, "__MISS__")

    def set(self, key: str, value) -> None:
        with self._lock:
            self.data[key] = value
            self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
        self._dirty = False

    @property
    def hits(self) -> int:
        return sum(1 for v in self.data.values() if v)


# ------------------------------------------------------- offline gazetteer
class OfflineUS:
    """US town and county centroids from the bundled `zipcodes` dataset."""

    def __init__(self):
        self.city: dict = {}
        self.county: dict = {}
        self.city_names: dict = {}
        self.city_county: dict = {}         # (state, city) -> proper-cased county name
        self.available = False
        try:
            import zipcodes  # type: ignore
        except Exception:
            return
        county_votes: dict = {}
        for z in zipcodes.list_all():
            try:
                lat, lon = float(z["lat"]), float(z["long"])
            except (TypeError, ValueError, KeyError):
                continue
            st = z["state"]
            city = (z.get("city") or "").lower()
            county_name = re.sub(r"\s+(County|Parish)$", "", z.get("county") or "", flags=re.I).strip()
            if city:
                self.city.setdefault((st, city), []).append((lat, lon))
                self.city_names.setdefault(st, set()).add(city)
                if county_name:
                    county_votes.setdefault((st, city), collections.Counter())[county_name] += 1
            if county_name:
                self.county.setdefault((st, county_name.lower()), []).append((lat, lon))
        # A (state, city) pair can span more than one ZIP record -- rare, but
        # occasionally a couple of them disagree on county. Go with whichever
        # county most of that city's ZIP records actually named.
        self.city_county = {k: v.most_common(1)[0][0] for k, v in county_votes.items()}
        self.available = True

    @staticmethod
    def _centroid(pts):
        return (round(statistics.median(p[0] for p in pts), 5),
                round(statistics.median(p[1] for p in pts), 5))

    def lookup(self, ref: PlaceRef) -> GeoResult:
        if not self.available or not ref.is_us or not ref.region_code:
            return GeoResult()
        st = ref.region_code
        loc = (ref.locality or "").strip()
        cands = [loc,
                 re.sub(r"\s+(Township|Twp|Village|City|Town|Ward\s*\d*|Borough|Precinct)\.?$",
                        "", loc, flags=re.I).strip(),
                 re.sub(r"^(North|South|East|West|St|Saint)\s+", "", loc).strip()]
        for c in filter(None, cands):
            pts = self.city.get((st, c.lower()))
            if pts:
                lat, lon = self._centroid(pts)
                self._backfill_county(ref, st, c.lower())
                return GeoResult(lat, lon, "city", "offline", ref.label())
        # "Mayfield" -> "Mayfield Heights" / "Mayfield Village"
        for c in filter(None, cands):
            cl = c.lower()
            names = self.city_names.get(st) or set()
            hits = sorted(n for n in names if n.startswith(cl + " "))
            if hits:
                pts = [p for h in hits for p in self.city[(st, h)]]
                lat, lon = self._centroid(pts)
                self._backfill_county(ref, st, hits[0])
                return GeoResult(lat, lon, "city (nearest named match)", "offline", ref.label())
        if ref.subregion:
            pts = self.county.get((st, ref.subregion.lower()))
            if pts:
                lat, lon = self._centroid(pts)
                note = "county centroid" + (" (small place not in gazetteer)" if loc else "")
                return GeoResult(lat, lon, note, "offline", ref.label())
        return GeoResult()

    def _backfill_county(self, ref: PlaceRef, state_code: str, city_key: str) -> None:
        """Fill in a county the raw place string never mentioned, from the same
        ZIP-code gazetteer record that just matched this city -- never
        overwrites a county the string parser already found."""
        if ref.subregion:
            return
        county = self.city_county.get((state_code, city_key))
        if county:
            ref.subregion = county


# ------------------------------------------------------------- Nominatim
class NominatimTier:
    def __init__(self, user_agent: str = NOMINATIM_UA, min_delay: float = MIN_DELAY_S):
        self.min_delay = min_delay
        self._last = 0.0
        self._geo = None
        self.enabled = True
        try:
            from geopy.geocoders import Nominatim  # type: ignore
            self._geo = Nominatim(user_agent=user_agent, timeout=12)
        except Exception:
            self.enabled = False

    def lookup(self, query: str) -> GeoResult:
        if not self.enabled or not self._geo or not query:
            return GeoResult()
        wait = self.min_delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        try:
            loc = self._geo.geocode(query, addressdetails=False)
        except Exception:
            return GeoResult()
        if not loc:
            return GeoResult()
        return GeoResult(round(loc.latitude, 6), round(loc.longitude, 6),
                         "nominatim", "nominatim", getattr(loc, "address", "") or query)


# ------------------------------------------------------------- the service
@dataclass
class Geocoder:
    cache: LocationCache
    use_offline: bool = True
    use_network: bool = True
    counties: dict = field(default_factory=dict)
    _offline: Optional[OfflineUS] = None
    _net: Optional[NominatimTier] = None
    stats: dict = field(default_factory=lambda: {"cache": 0, "offline": 0,
                                                 "nominatim": 0, "failed": 0})

    def __post_init__(self):
        if not self.counties:
            self.counties = counties_index_from_zipcodes()
        if self.use_offline and self._offline is None:
            self._offline = OfflineUS()
        if self.use_network and self._net is None:
            self._net = NominatimTier()

    def resolve(self, raw_place: str) -> tuple[Optional[PlaceRef], GeoResult]:
        ref = parse_place(raw_place, self.counties)
        if ref is None:
            return None, GeoResult()

        key = raw_place.strip()
        cached = self.cache.get(key)
        if cached != "__MISS__":
            if not cached:
                self.stats["failed"] += 1
                return ref, GeoResult()
            self.stats["cache"] += 1
            r = GeoResult(cached.get("lat"), cached.get("lon"),
                         cached.get("precision", "cached"), "cache",
                         cached.get("address", ""))
            self._backfill_subregion(ref, r.display)
            if not ref.subregion and self._offline:
                # A cached result from the offline tier stores only ref.label() as
                # its "address" -- self-referential, nothing new to parse out of it.
                # Consult the gazetteer's fast in-memory city->county map directly
                # instead, so a place resolved (and cached) before this fix existed
                # still gets its county filled in on the next run, with no new
                # lookup and no need to clear the cache.
                self._offline.lookup(ref)
            return ref, r

        if self._offline:
            r = self._offline.lookup(ref)
            if r.ok:
                self.stats["offline"] += 1
                self.cache.set(key, {"lat": r.lat, "lon": r.lon,
                                     "precision": r.precision, "address": r.display})
                return ref, r

        network_ran = False
        if self._net and self._net.enabled:
            network_ran = True
            r = self._net.lookup(ref.geocode_query())
            if r.ok:
                self.stats["nominatim"] += 1
                # Nominatim's own address string usually names the county even when
                # the GEDCOM place string never did ("Lincklaen, New York, USA" comes
                # back as "Lincklaen, Chenango County, New York, ..."). Recover it
                # rather than reporting the county as unspecified when the geocoder
                # itself just told us what it is.
                self._backfill_subregion(ref, r.display)
                self.cache.set(key, {"lat": r.lat, "lon": r.lon,
                                     "precision": r.precision, "address": r.display})
                return ref, r

        self.stats["failed"] += 1
        # Only record a permanent failure when the network tier actually ran and
        # came back empty. Caching a miss that merely reflects "network was off"
        # would poison the cache for every later run.
        if network_ran:
            self.cache.set(key, None)
        return ref, GeoResult()

    @staticmethod
    def _backfill_subregion(ref: PlaceRef, address: str) -> None:
        """Fill in a county the raw place string never mentioned, when the
        geocoder's own address string names one. Never overwrites a county the
        string parser already found -- that one came from the source record
        itself and outranks one merely inferred from a geocoder response."""
        if ref.subregion or not address:
            return
        for part in address.split(","):
            m = COUNTY_SUFFIX.match(part.strip())
            if m:
                ref.subregion = _subregion_name(m.group(1), m.group(2))
                return

    def resolve_many(self, places, progress: Optional[Callable[[int, int, str], None]] = None):
        places = list(dict.fromkeys(p for p in places if p and p.strip()))
        out = {}
        for i, p in enumerate(places, 1):
            out[p] = self.resolve(p)
            if progress:
                progress(i, len(places), p)
        self.cache.save()
        return out

    def estimate_network_calls(self, places) -> int:
        """How many uncached, offline-unresolvable places remain. Drives the UI warning."""
        n = 0
        for p in dict.fromkeys(x for x in places if x and x.strip()):
            if self.cache.get(p.strip()) != "__MISS__":
                continue
            ref = parse_place(p, self.counties)
            if ref and self._offline and self._offline.lookup(ref).ok:
                continue
            n += 1
        return n
