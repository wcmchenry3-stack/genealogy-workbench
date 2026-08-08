#!/usr/bin/env python
# coding: utf-8

# In[ ]:


#!/usr/bin/env python
# coding: utf-8

import os
import json
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, Iterable

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable


# ----------------------------
# Progress tracker (unchanged)
# ----------------------------
class ProgressTracker:
    def __init__(self, total: int, label: str = "Geocoding"):
        self.total = max(int(total), 0)
        self.label = label
        self.start = time.time()
        self.done = 0
        self.successes = 0
        self.failures = 0
        self.cache_hits = 0
        self.skips = 0

    def update(self, event: str, location: str, source: str, ok: Optional[bool]):
        if event == "skip":
            self.skips += 1
            self.done += 1
        elif event == "cache_hit":
            self.cache_hits += 1
            self.done += 1
        elif event == "success":
            self.successes += 1
            self.done += 1
        elif event == "fail":
            self.failures += 1
            self.done += 1

        self._render(location=location, source=source, ok=ok)

    def _render(self, location: str = "", source: str = "", ok: Optional[bool] = None):
        elapsed = time.time() - self.start
        rate = (self.done / elapsed) if elapsed > 0 and self.done > 0 else 0.0
        remaining = max(self.total - self.done, 0)
        eta = (remaining / rate) if rate > 0 else 0.0

        status = ""
        if ok is True:
            status = "✅"
        elif ok is False:
            status = "❌"
        elif ok is None:
            status = "…"

        msg = (
            f"\r{self.label}: {self.done}/{self.total} "
            f"(✅{self.successes} ❌{self.failures} 💾{self.cache_hits} ⏭️{self.skips}) "
            f"| ETA {eta:0.0f}s | {status} {source} {location[:50]}"
        )
        print(msg, end="")

    def finish(self):
        print()  # newline
        elapsed = time.time() - self.start
        print(
            f"✅ {self.label} finished in {elapsed:0.1f}s "
            f"(✅{self.successes} ❌{self.failures} 💾{self.cache_hits} ⏭️{self.skips})"
        )


# ----------------------------
# Refactor: library + service
# ----------------------------
@dataclass
class LocationLibrary:
    path: str
    data: Dict[str, Any]

    @classmethod
    def load(cls, path: str) -> "LocationLibrary":
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                print(f"🌍 Location Library Loaded: {len(data)} entries.")
                return cls(path=path, data=data)
            except Exception:
                print("⚠️ Error loading location library. Starting fresh.")
                return cls(path=path, data={})
        else:
            print("🌍 Creating new location library.")
            return cls(path=path, data={})

    def save(self):
        if not self.path:
            return
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f)
        print("💾 Location Library saved.")

    def get(self, key: str):
        return self.data.get(key)

    def has(self, key: str) -> bool:
        return key in self.data

    def set(self, key: str, value: Any):
        self.data[key] = value


class NominatimClient:
    def __init__(self, user_agent: str = "ancestry_manager_v1", timeout: int = 10, min_delay_s: float = 1.5):
        self.min_delay_s = float(min_delay_s)
        self.geolocator = Nominatim(user_agent=user_agent, timeout=timeout)

    def geocode(self, location_name: str) -> Optional[Dict[str, Any]]:
        # Rate limiting
        time.sleep(self.min_delay_s)
        loc = self.geolocator.geocode(location_name)
        if not loc:
            return None
        return {"lat": loc.latitude, "lon": loc.longitude, "address": loc.address}


class GeocodingService:
    def __init__(self, library: LocationLibrary, client: Optional[NominatimClient] = None):
        self.library = library
        self.client = client or NominatimClient()

    def get_coords(self, location_name: str, progress_cb=None) -> Optional[Dict[str, Any]]:
        """
        Backward-compatible behavior:
        - Skip short/empty
        - Cache hit returns cached value (including None)
        - API call stores dict or None
        - Timeout/unavailable caches None to avoid hammering
        """
        if not location_name or len(str(location_name)) < 4:
            if progress_cb:
                progress_cb(event="skip", location=str(location_name), source="skip", ok=None)
            return None

        # 1) Library cache
        if self.library.has(location_name):
            val = self.library.get(location_name)
            if progress_cb:
                progress_cb(event="cache_hit", location=location_name, source="cache", ok=(val is not None))
            return val

        # 2) API
        try:
            if progress_cb:
                progress_cb(event="api_call", location=location_name, source="api", ok=None)

            data = self.client.geocode(location_name)
            if data:
                self.library.set(location_name, data)
                if progress_cb:
                    progress_cb(event="success", location=location_name, source="api", ok=True)
                return data
            else:
                self.library.set(location_name, None)  # cache failure
                if progress_cb:
                    progress_cb(event="fail", location=location_name, source="api", ok=False)
                return None

        except (GeocoderTimedOut, GeocoderUnavailable) as e:
            print(f"\n   [!] Geo-lookup failed (timeout/unavailable): {location_name} ({e})")
            self.library.set(location_name, None)
            if progress_cb:
                progress_cb(event="fail", location=location_name, source="api", ok=False)
            return None

        except Exception as e:
            print(f"\n   [!] Geo-lookup failed: {location_name} ({e})")
            if progress_cb:
                progress_cb(event="fail", location=location_name, source="api", ok=False)
            return None


# ----------------------------
# Backward-compatible wrappers
# ----------------------------
_SERVICE: Optional[GeocodingService] = None


def load_library(path: str):
    global _SERVICE
    lib = LocationLibrary.load(path)
    _SERVICE = GeocodingService(lib)


def save_library():
    if _SERVICE and _SERVICE.library:
        _SERVICE.library.save()


def get_coords(location_name, progress_cb=None):
    """
    Wrapper kept for compatibility with existing scripts.
    """
    global _SERVICE
    # Allow running even if caller forgot load_library(); it just won't persist
    if _SERVICE is None:
        _SERVICE = GeocodingService(LocationLibrary(path="", data={}))
    result = _SERVICE.get_coords(location_name, progress_cb=progress_cb)
    # Persist after new keys are added when a path exists
    if _SERVICE.library.path:
        _SERVICE.library.save()
    return result


def geocode_many(location_names: Iterable[str], tracker: ProgressTracker | None = None):
    """
    Batch helper: shows progress automatically, returns dict of location -> coords (or None).
    """
    names = list(location_names)
    if tracker is None:
        tracker = ProgressTracker(total=len(names), label="Geocoding")

    results = {}
    for name in names:
        results[name] = get_coords(name, progress_cb=tracker.update)

    tracker.finish()
    return results
