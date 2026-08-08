#!/usr/bin/env python
# coding: utf-8
from __future__ import annotations

# In[ ]:


#!/usr/bin/env python3
# coding: utf-8
"""
gedcom_cleaner.py
-----------------
Reads GEDCOM via gedcom_parser.parse_gedcom and writes master_tree.csv.

Milestone 4 refactor:
- Encapsulate geocode/place cleaning inside a class
- Keep public API functions unchanged
"""


import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple, Optional

from gedcom_parser import parse_gedcom
from gedcom_geocoder import get_coords, save_library


# ----------------------------
# Date cleaning (public API)
# ----------------------------
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
}
_YEAR_RE = re.compile(r"\b(\d{4})\b")


def clean_date(s: str) -> Tuple[str, str]:
    """
    Returns: (clean_date, precision)
    clean_date formats:
      - YYYY
      - YYYY-MM
      - YYYY-MM-DD
      - YYYY-YYYY (range) for BET/AND cases

    precision:
      - "year" | "month" | "day" | "range" | "unknown"
    """
    if not s:
        return "", "unknown"

    s = str(s).strip().upper()
    if not s:
        return "", "unknown"

    # Range: "BET 1900 AND 1905"
    if s.startswith("BET ") and " AND " in s:
        parts = s.replace("BET ", "").split(" AND ")
        y1 = _extract_year(parts[0])
        y2 = _extract_year(parts[1])
        if y1 and y2:
            lo, hi = min(y1, y2), max(y1, y2)
            return f"{lo}-{hi}", "range"

    # Common GEDCOM: "DD MMM YYYY" or "MMM YYYY" or "YYYY"
    tokens = s.split()
    if len(tokens) == 1:
        y = _extract_year(tokens[0])
        return (str(y), "year") if y else ("", "unknown")

    if len(tokens) == 2:
        # "MMM YYYY"
        m = _MONTHS.get(tokens[0][:3])
        y = _extract_year(tokens[1])
        if m and y:
            return f"{y:04d}-{m:02d}", "month"

    if len(tokens) >= 3:
        # "DD MMM YYYY"
        try:
            d = int(tokens[0])
        except Exception:
            d = None
        m = _MONTHS.get(tokens[1][:3])
        y = _extract_year(tokens[2])
        if d and m and y:
            return f"{y:04d}-{m:02d}-{d:02d}", "day"

    # fallback: any year in string
    y = _extract_year(s)
    return (str(y), "year") if y else ("", "unknown")


def _extract_year(s: str) -> Optional[int]:
    m = _YEAR_RE.search(str(s))
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


# ----------------------------
# Address overrides (public API)
# ----------------------------
def load_address_overrides(csv_path: Path) -> dict:
    overrides = {}
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row.get("original_place") or "").strip().lower()
                if not key:
                    continue
                overrides[key] = {
                    "address": (row.get("clean_address") or "").strip(),
                    "lat": (row.get("lat") or "").strip(),
                    "lon": (row.get("lon") or "").strip(),
                }
    except FileNotFoundError:
        print("⚠️ address_override.csv not found — overrides disabled")
    return overrides


def _safe_place_attr(person_obj, attr: str) -> str:
    v = getattr(person_obj, attr, "") or ""
    return str(v).strip()


# ----------------------------
# Cleaner class (internal)
# ----------------------------
@dataclass
class GedcomCleaner:
    address_overrides: Dict[str, Dict[str, str]]

    def geocode_place(self, original_place: str) -> Tuple[str, str, str]:
        """
        Precedence:
          1) address_override.csv
          2) geocoder + cache
          3) original GEDCOM string
        """
        if not original_place:
            return "", "", ""

        key = original_place.strip().lower()

        # 1) override
        if key in self.address_overrides:
            o = self.address_overrides[key]
            return (o.get("lat", ""), o.get("lon", ""), o.get("address") or original_place)

        # 2) geocoder/cache
        coords = get_coords(original_place)
        if not coords:
            return "", "", original_place

        lat = coords.get("lat", "")
        lon = coords.get("lon", "")
        clean = coords.get("address") or original_place
        return lat, lon, clean


def process_gedcom_to_csv(
    *,
    gedcom_path: str,
    output_csv_path: str,
    address_overrides: dict,
) -> None:
    """
    Public API (unchanged signature style used by controller).

    Produces master_tree.csv with cleaned date/place fields + parent IDs.
    """
    inds, fams = parse_gedcom(gedcom_path, show_progress=True)
    cleaner = GedcomCleaner(address_overrides=address_overrides)

    fieldnames = [
        "ID", "Name", "Sex",
        "BirtDate_Orig", "BirtDate_Clean", "BirtDate_Precision",
        "DeatDate_Orig", "DeatDate_Clean", "DeatDate_Precision",
        "MarrDate_Orig", "MarrDate_Clean", "MarrDate_Precision",
        "BirtPlace", "BirtPlace_Clean", "BirtLat", "BirtLon",
        "DeatPlace", "DeatPlace_Clean", "DeatLat", "DeatLon",
        "FatherID", "MotherID",
    ]

    total = len(inds)
    with open(output_csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()

        for count, (pid, p) in enumerate(inds.items(), start=1):
            # Periodically flush the location library
            if count % 50 == 0:
                print(f"   Processing {count}/{total}...")
                save_library()

            birt_clean, birt_prec = clean_date(getattr(p, "birt_date", "") or "")
            deat_clean, deat_prec = clean_date(getattr(p, "deat_date", "") or "")
            marr_clean, marr_prec = clean_date(getattr(p, "marr_date", "") or "")

            birt_place_orig = _safe_place_attr(p, "birt_place")
            deat_place_orig = _safe_place_attr(p, "deat_place")

            birt_lat, birt_lon, birt_place_clean = cleaner.geocode_place(birt_place_orig)
            deat_lat, deat_lon, deat_place_clean = cleaner.geocode_place(deat_place_orig)

            # Parent IDs via FAMC
            fid = mid = ""
            famc = getattr(p, "famc", None)
            if famc and famc in fams:
                fam = fams[famc]
                fid = getattr(fam, "husb", "") or ""
                mid = getattr(fam, "wife", "") or ""

            w.writerow({
                "ID": pid,
                "Name": getattr(p, "name", "") or "",
                "Sex": getattr(p, "sex", "") or "",
                "BirtDate_Orig": getattr(p, "birt_date", "") or "",
                "BirtDate_Clean": birt_clean,
                "BirtDate_Precision": birt_prec,
                "DeatDate_Orig": getattr(p, "deat_date", "") or "",
                "DeatDate_Clean": deat_clean,
                "DeatDate_Precision": deat_prec,
                "MarrDate_Orig": getattr(p, "marr_date", "") or "",
                "MarrDate_Clean": marr_clean,
                "MarrDate_Precision": marr_prec,
                "BirtPlace": birt_place_orig,
                "BirtPlace_Clean": birt_place_clean,
                "BirtLat": birt_lat,
                "BirtLon": birt_lon,
                "DeatPlace": deat_place_orig,
                "DeatPlace_Clean": deat_place_clean,
                "DeatLat": deat_lat,
                "DeatLon": deat_lon,
                "FatherID": fid,
                "MotherID": mid,
            })

    # final save
    save_library()
    print(f"✅ Wrote master CSV: {output_csv_path}")
