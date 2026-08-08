#!/usr/bin/env python3
"""
core/places.py
--------------
Worldwide place-string resolution.

GEDCOM place strings are free text with no schema -- "Cleveland, Cuyahoga, Ohio,
USA", "Wheeling, Ohio County, West Virginia", "Chrastice 1, Central Bohemia,
Czech Republic", "Ellastone, Staffordshire, England". This module turns them
into a structured PlaceRef so that reports can group, filter and map them.

Design notes
------------
* Nothing here assumes the United States. The US simply gets an extra level
  (county) that most countries do not use.
* Two traps this handles explicitly, both present in real Ancestry exports:
    - "Wheeling, Ohio, West Virginia"  -> Ohio COUNTY, West Virginia. Not Ohio.
    - "Steubenville, Jefferson County  Ohio" -> missing comma before the state.
* Historical place names (Bohemia, Prussia, Colonial America) are preserved for
  display but mapped to a modern country so geocoding has something to work with.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

# --------------------------------------------------------------- US states
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin",
    "WY": "Wyoming", "DC": "District of Columbia",
}
STATE_LOOKUP: dict[str, str] = {}
for _ab, _full in US_STATES.items():
    STATE_LOOKUP[_full.lower()] = _ab
    STATE_LOOKUP[_ab.lower()] = _ab
for _alias, _ab in [
    ("w. va", "WV"), ("w va", "WV"), ("wva", "WV"), ("mich", "MI"), ("penn", "PA"),
    ("penna", "PA"), ("calif", "CA"), ("mass", "MA"), ("conn", "CT"), ("tenn", "TN"),
    ("wisc", "WI"), ("ills", "IL"), ("n. y", "NY"), ("n y", "NY"), ("va", "VA"),
]:
    STATE_LOOKUP.setdefault(_alias, _ab)

# Canadian provinces get the same treatment -- second most common country here.
CA_PROVINCES = {
    "ON": "Ontario", "QC": "Quebec", "NS": "Nova Scotia", "NB": "New Brunswick",
    "MB": "Manitoba", "BC": "British Columbia", "PE": "Prince Edward Island",
    "SK": "Saskatchewan", "AB": "Alberta", "NL": "Newfoundland and Labrador",
    "NT": "Northwest Territories", "YT": "Yukon", "NU": "Nunavut",
}

# ------------------------------------------------------------- countries
# name (lowercase) -> (display country, ISO-ish code used for grouping)
# Historical names map onto a modern country so the geocoder has a target,
# while `historical` keeps the original wording for display.
COUNTRIES: dict[str, tuple[str, str]] = {}

def _reg(code: str, display: str, *aliases: str) -> None:
    COUNTRIES[display.lower()] = (display, code)
    for a in aliases:
        COUNTRIES[a.lower()] = (display, code)

_reg("US", "United States", "usa", "us", "u.s.a.", "u.s.", "united states of america",
     "america", "united states of america.")
_reg("GB", "England", "eng")
_reg("GB", "Scotland", "scot")
_reg("GB", "Wales")
_reg("GB", "Northern Ireland")
_reg("GB", "United Kingdom", "uk", "u.k.", "great britain", "britain")
_reg("IE", "Ireland", "eire", "republic of ireland")
_reg("CA", "Canada")
_reg("FR", "France")
_reg("DE", "Germany", "deutschland", "allemagne")
_reg("NL", "Netherlands", "holland", "the netherlands")
_reg("BE", "Belgium")
_reg("CH", "Switzerland")
_reg("AT", "Austria", "osterreich")
_reg("CZ", "Czech Republic", "czechia", "czechoslovakia")
_reg("IT", "Italy", "italia")
_reg("ES", "Spain")
_reg("PT", "Portugal")
_reg("PL", "Poland", "polska")
_reg("SE", "Sweden"); _reg("NO", "Norway"); _reg("DK", "Denmark"); _reg("FI", "Finland")
_reg("RU", "Russia"); _reg("UA", "Ukraine"); _reg("HU", "Hungary"); _reg("RO", "Romania")
_reg("GR", "Greece"); _reg("TR", "Turkey"); _reg("MX", "Mexico"); _reg("AU", "Australia")
_reg("NZ", "New Zealand"); _reg("ZA", "South Africa"); _reg("IN", "India")
_reg("JM", "Jamaica"); _reg("BB", "Barbados"); _reg("BM", "Bermuda")
_reg("LU", "Luxembourg"); _reg("SK", "Slovakia"); _reg("SI", "Slovenia")
_reg("HR", "Croatia"); _reg("RS", "Serbia"); _reg("BG", "Bulgaria")
_reg("EG", "Egypt"); _reg("IL", "Israel"); _reg("PA", "Panama"); _reg("AW", "Aruba")
_reg("CU", "Cuba"); _reg("PR", "Puerto Rico"); _reg("PH", "Philippines")
_reg("JP", "Japan"); _reg("CN", "China"); _reg("BR", "Brazil"); _reg("AR", "Argentina")
_reg("IS", "Iceland"); _reg("EE", "Estonia"); _reg("LV", "Latvia"); _reg("LT", "Lithuania")

# Ancestry exports sometimes carry French/German locale spellings of countries.
for _fr, _en in [
    ("pays-bas", "Netherlands"), ("angleterre", "England"), ("ecosse", "Scotland"),
    ("irlande", "Ireland"), ("suisse", "Switzerland"), ("espagne", "Spain"),
    ("italie", "Italy"), ("belgique", "Belgium"), ("danemark", "Denmark"),
    ("norvege", "Norway"), ("suede", "Sweden"), ("russie", "Russia"),
    ("autriche", "Austria"), ("hongrie", "Hungary"), ("pologne", "Poland"),
    ("etats-unis", "United States"), ("royaume-uni", "United Kingdom"),
    ("frankreich", "France"), ("niederlande", "Netherlands"),
    ("grossbritannien", "United Kingdom"), ("oesterreich", "Austria"),
]:
    COUNTRIES[_fr] = COUNTRIES[_en.lower()]

# Historical / imprecise names → modern country, original wording preserved.
HISTORICAL: dict[str, tuple[str, str]] = {
    "bohemia": ("Czech Republic", "CZ"),
    "moravia": ("Czech Republic", "CZ"),
    "central bohemia": ("Czech Republic", "CZ"),
    "prussia": ("Germany", "DE"),
    "preussen": ("Germany", "DE"),
    "bavaria": ("Germany", "DE"),
    "hesse": ("Germany", "DE"),
    "saarland": ("Germany", "DE"),
    "westphalia": ("Germany", "DE"),
    "colonial america": ("United States", "US"),
    "british colonial america": ("United States", "US"),
    "british america": ("United States", "US"),
    "new france": ("Canada", "CA"),
    "upper canada": ("Canada", "CA"),
    "lower canada": ("Canada", "CA"),
    "austria-hungary": ("Austria", "AT"),
    "austro-hungarian empire": ("Austria", "AT"),
    "galicia": ("Poland", "PL"),
    "silesia": ("Poland", "PL"),
    "pomerania": ("Poland", "PL"),
    "alsace-lorraine": ("France", "FR"),
    "alsace": ("France", "FR"),
    "lorraine": ("France", "FR"),
    "baden": ("Germany", "DE"),
    "wurttemberg": ("Germany", "DE"),
    "wuerttemberg": ("Germany", "DE"),
    "saxony": ("Germany", "DE"),
    "hanover": ("Germany", "DE"),
    "nassau": ("Germany", "DE"),
    "rhineland": ("Germany", "DE"),
    "mecklenburg": ("Germany", "DE"),
    "holstein": ("Germany", "DE"),
    "schleswig": ("Germany", "DE"),
    "austria / hungary": ("Austria", "AT"),
    "panama canal zone": ("Panama", "PA"),
    "new netherland": ("United States", "US"),
    "new sweden": ("United States", "US"),
    "province of canada": ("Canada", "CA"),
}

COUNTY_SUFFIX = re.compile(r"^(.*?)[\s,]+(County|Co|Parish|Shire|Borough|Planning Region)\.?$", re.I)


def _subregion_name(name: str, suffix: str) -> str:
    """Build the stored subregion value from a COUNTY_SUFFIX match.

    "County"/"Co"/"Parish"/"Shire"/"Borough" get stripped -- PlaceRef.label()
    re-adds a short " Co." for display. Connecticut's post-2022 "planning
    region" isn't a county and reads oddly with that same abbreviation
    ("Southeastern Connecticut Co." names nothing real), so its full name is
    kept as the subregion value itself; label() and the report hierarchy
    headers detect that by the trailing "region" and leave it alone."""
    name = name.strip()
    return f"{name} Planning Region" if suffix.strip().lower() == "planning region" else name


def subregion_is_self_describing(subregion: str) -> bool:
    """True when a subregion value already names what kind of thing it is
    (Connecticut's "Xxx Planning Region"), so display code should use it as-is
    instead of appending the "County"/"Co." that fits an ordinary county."""
    return (subregion or "").strip().lower().endswith("region")
CEMETERY_LEAD = re.compile(
    r"^(.*?(?:Cemetery|Cemeteries|Memorial Gardens|Memorial Park|Burial Ground|"
    r"Churchyard|Graveyard|Mausoleum))\s*,\s*(.*)$", re.I)
SUBDIVISION = re.compile(
    r"\s+(Township|Twp|Village|City|Town|Ward\s*\d*|Borough|Precinct|District|Parish)\.?$", re.I)


@dataclass
class PlaceRef:
    """A resolved place. `country_code` is None only when nothing was recognised."""
    raw: str
    locality: Optional[str] = None      # town / village / township
    subregion: Optional[str] = None     # US county (or CT's post-2022 "planning region"), UK shire
    region: Optional[str] = None        # US state, CA province, or foreign region
    region_code: Optional[str] = None   # "OH" when region is a US state
    country: Optional[str] = None       # display name ("England", not "GB")
    country_code: Optional[str] = None
    historical: Optional[str] = None    # original wording when remapped
    cemetery: Optional[str] = None      # when the PLAC field led with one
    note: Optional[str] = None

    @property
    def resolved(self) -> bool:
        return self.country_code is not None

    @property
    def is_us(self) -> bool:
        return self.country_code == "US"

    def key(self) -> tuple:
        """Canonical identity -- what makes two place strings 'the same place'."""
        return (self.country_code or "??", (self.region or "").title(),
                (self.subregion or "").title(), (self.locality or "").title())

    def label(self) -> str:
        bits = [self.locality]
        if self.subregion:
            if self.is_us and not subregion_is_self_describing(self.subregion):
                bits.append(f"{self.subregion} Co.")
            else:
                bits.append(self.subregion)
        bits.append(self.region_code if self.is_us and self.region_code else self.region)
        if not self.is_us:
            bits.append(self.historical or self.country)
        return ", ".join(b for b in bits if b) or (self.raw or "Unknown")

    def geocode_query(self) -> str:
        """A string worth handing to a geocoder -- modern names, no cemetery prefix."""
        bits = [self.locality, self.subregion, self.region, self.country]
        return ", ".join(b for b in bits if b) or self.raw


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _tok(t: str) -> str:
    return re.sub(r"\s+", " ", _strip_accents(t).strip().strip(".").strip())


# Documented manual corrections, each justified by other evidence in the tree.
PLACE_FIXES: dict[str, dict] = {
    "wakeshema": dict(locality="Fulton", subregion="Kalamazoo", region="Michigan",
                      region_code="MI", country="United States", country_code="US",
                      note="GEDCOM spells it 'Wakeshema'; Wakeshma Twp, Kalamazoo Co."),
}


def parse_place(raw: str, counties_for: Optional[dict] = None) -> Optional[PlaceRef]:
    """Resolve a GEDCOM place string.

    `counties_for` is an optional {state_code: {county names}} map used to tell a
    county apart from a town when the string gives no "County" suffix. Without it
    the parser still works, just a little less precisely.
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip()

    cemetery = None
    m = CEMETERY_LEAD.match(text)
    if m:
        cemetery, text = m.group(1).strip(), m.group(2)

    parts = [p for p in (_tok(p) for p in text.split(",")) if p]
    if not parts:
        return None

    fix = PLACE_FIXES.get(parts[0].lower())
    if fix:
        return PlaceRef(raw=raw, cemetery=cemetery, **fix)

    ref = PlaceRef(raw=raw, cemetery=cemetery)

    # ---- 1. country, from the tail -------------------------------------
    def _country_of(tokens: list[str]) -> bool:
        while tokens:
            low = tokens[-1].lower()
            if low in COUNTRIES:
                ref.country, ref.country_code = COUNTRIES[low]
                if ref.country.lower() != low:
                    ref.historical = tokens[-1]
                tokens.pop()
                return True
            if low in HISTORICAL:
                ref.country, ref.country_code = HISTORICAL[low]
                ref.historical = tokens[-1]
                tokens.pop()
                return True
            return False
        return False

    _country_of(parts)

    # ---- 2. region: US state / CA province / free-text region ----------
    if parts:
        low = parts[-1].lower()
        if (ref.country_code in (None, "US")) and low in STATE_LOOKUP:
            ref.region_code = STATE_LOOKUP[parts.pop().lower()]
            ref.region = US_STATES[ref.region_code]
            ref.country, ref.country_code = "United States", "US"
        elif ref.country_code == "CA" and parts[-1].title() in CA_PROVINCES.values():
            ref.region = parts.pop().title()
        elif ref.country_code is None:
            # Missing comma before the state: "Jefferson County  Ohio"
            last = parts[-1]
            for nm in sorted((n for n in STATE_LOOKUP if len(n) >= 4), key=len, reverse=True):
                mm = re.match(rf"^(.*?)[\s,]+{re.escape(nm)}$", last, re.I)
                if mm:
                    ref.region_code = STATE_LOOKUP[nm]
                    ref.region = US_STATES[ref.region_code]
                    ref.country, ref.country_code = "United States", "US"
                    parts[-1] = mm.group(1).strip()
                    if not parts[-1]:
                        parts.pop()
                    break

    # ---- 3. county / shire ---------------------------------------------
    for i in range(len(parts) - 1, -1, -1):
        mm = COUNTY_SUFFIX.match(parts[i])
        if mm:
            ref.subregion = _subregion_name(mm.group(1), mm.group(2))
            parts.pop(i)
            break
    if ref.subregion is None and counties_for and ref.region_code:
        pool = counties_for.get(ref.region_code) or set()
        for i in range(len(parts) - 1, -1, -1):
            if parts[i].lower() in pool:
                ref.subregion = parts.pop(i)
                break

    # ---- 4. region for non-US places ------------------------------------
    # "Ellastone, Staffordshire, England" -> Staffordshire is the region.
    # Only claim one when something is left in front to be the locality,
    # so "Cork, Ireland" keeps Cork as the town rather than demoting it.
    if not ref.region and len(parts) >= 2 and not ref.is_us:
        ref.region = parts.pop()

    # ---- 5. whatever is left in front is the locality --------------------
    for p in parts:
        if p and not re.fullmatch(r"\d+", p):
            ref.locality = p
            break
    if ref.locality and ref.subregion and ref.locality.lower() == ref.subregion.lower():
        ref.locality = None

    return ref


def counties_index_from_zipcodes() -> dict:
    """{state_code: {lowercased county names}} from the offline gazetteer, if present."""
    try:
        import zipcodes  # type: ignore
    except Exception:
        return {}
    out: dict[str, set] = {}
    for z in zipcodes.list_all():
        c = z.get("county")
        if c:
            out.setdefault(z["state"], set()).add(
                re.sub(r"\s+(County|Parish|Borough|Census Area)$", "", c, flags=re.I).lower())
    return out
