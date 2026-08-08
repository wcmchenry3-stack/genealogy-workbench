# Code guide

A developer's companion to the [README](../README.md). The README says how to
*use* the app; this says how it *works* and where to change it.

---

## Layout

```
genealogy-workbench/
├── run.bat / run.sh        launcher: venv, deps, server, browser
├── requirements.txt
├── app/                    the web layer
│   ├── server.py           Flask routes, background job runner
│   ├── run_context.py      per-run directory bookkeeping
│   ├── run_logger.py       append-only run log
│   └── templates/index.html   the entire UI, one file, no build step
├── core/                   parsing, tracing, place resolution, geocoding
├── reports/                all eight reports + registry + shared theme
├── data/                   caches and manual corrections (persist across runs)
└── runs/                   timestamped outputs (gitignored)
```

Two rules hold the shape together:

1. **`core/` never imports from `reports/`.** Data flows one way.
2. **Reports never talk to each other**, except through a published file — see
   `place_anchors.json` under *Cross-report links*.

---

## The two data files

Everything downstream reads one or both. They are produced by a single pass in
`core/pipeline.py`.

### `data/master_tree.csv` — person-level

One row per person in the whole tree. **21 columns, fixed:**

```
ID, Name, Sex,
BirtDate_Orig, BirtDate_Clean, BirtDate_Precision,
DeatDate_Orig, DeatDate_Clean, DeatDate_Precision,
MarrDate_Orig, MarrDate_Clean, MarrDate_Precision,
BirtPlace, BirtPlace_Clean, BirtLat, BirtLon,
DeatPlace, DeatPlace_Clean, DeatLat, DeatLon,
FatherID, MotherID
```

> **Do not change this schema.** Five reports read it and were carried over
> unmodified. It is a contract, not an implementation detail. Note the spelling
> `Birt`/`Deat`, not `Birth`/`Death` — some readers defensively accept both.

Written by `gedcom_cleaner.process_gedcom_to_csv`, which is the original code,
untouched.

### `runs/<id>/events.csv` — event-level

One row per person **per dated place**. This is what `master_tree.csv` cannot
express: residences, censuses, burials, probate — everywhere a person appears
over time, not just their three life events.

```
PersonID, PersonName, Sex, Generation, Relationship, Line,
Event, Tag, Date, Year, DateQualifier,
PlaceRaw, Locality, Subregion, Region, RegionCode, Country, CountryCode,
PlaceKey, PlaceLabel, Lat, Lon, GeoPrecision, GeoSource,
Cemetery, CemeteryAddress, CemeteryPlot
```

`PlaceKey` is the canonical place identity — `"US|Ohio|Cuyahoga|Cleveland"` —
and is what groups events into places. `Line` is `paternal`/`maternal`/`self`.

Scoped to the traced ancestors, so it respects max-generations; `master_tree.csv`
always covers everyone.

---

## `core/` module by module

### `events.py` — the event-level GEDCOM reader

`load_tree(path) -> Tree` with `Tree.individuals` / `Tree.families`, each
`Individual` carrying a full `events` list.

There are deliberately **two parsers** in this codebase. `gedcom_parser.py`
(ported) produces the person-level view that feeds `master_tree.csv`.
`events.py` produces the event-level view. They are different shapes, not
duplicates, and reading a 5 MB file twice costs about 0.3 seconds. Rewriting the
ported parser to serve both would have meant editing logic that five working
reports depend on.

Also handles: `CONC`/`CONT` continuation folding, marriages copied onto both
spouses' timelines, and date parsing with qualifiers (`ABT`, `BEF`, `BET`).

### `ancestry.py` — the walk

`walk_ancestors(tree, root_id, max_generations) -> {id: Ancestor}`

Breadth-first up every parent line. Unconditional except for depth. Cycles — real
in genealogy, through cousin marriages or data errors — are visited once and not
re-expanded, so it always terminates.

> **Design note.** An earlier version pruned lines geographically, stopping when
> an ancestor was neither born nor died in a target state. That put one report's
> filter inside the shared data and is precisely why the tool could not go
> worldwide. Collect everything once; let each view filter.

`Ancestor.relationship` renders `father` → `grandmother` →
`great-great-grandfather`, switching to `12x great-grandfather` past three, since
this tree reaches 31 generations and spelling that out is unreadable.

### `places.py` — worldwide place resolution

`parse_place(raw, counties_for) -> PlaceRef`

Free-text GEDCOM place strings into structured `locality / subregion / region /
country`. Knows 60+ countries, French and German locale spellings (`Pays-Bas`,
`Allemagne`), and historical regions (`Bohemia`, `Prussia`, `Colonial America`)
which map to a modern country for geocoding while keeping the original wording
for display.

Two traps it handles explicitly, both real in Ancestry exports:

```
"Wheeling, Ohio, West Virginia"        -> Ohio COUNTY, West Virginia
"Steubenville, Jefferson County  Ohio" -> missing comma before the state
```

`PlaceRef.key()` is the canonical identity; `.label()` is for display;
`.geocode_query()` is the modern-name string handed to a geocoder.

Resolves about 94% of this tree's 3,843 distinct place strings structurally. The
rest — street addresses, `"?"`, `"Atlantic Ocean"` — still reach the geocoder as
raw text.

### `geocode.py` — three tiers

```
LocationCache  →  OfflineUS  →  NominatimTier
 (instant)        (instant)     (~1 req/sec)
```

Every tier writes back to `data/location_library.json`, shared with the original
pipeline. `GeoResult.precision` is always honest — a county centroid says so, and
the map surfaces that as a warning rather than implying a street match.

> **Careful here.** A failed lookup is cached as a permanent `null` **only when
> the network tier actually ran**. Caching a miss that merely reflects "network
> was switched off" would poison the cache for every later run. See
> `network_ran` in `Geocoder.resolve`.

`estimate_network_calls(places)` reports how many uncached, offline-unresolvable
places remain — call it *before* resolving, since resolving changes the answer.

### `pipeline.py` — the single pass

`run_pipeline(...) -> PipelineResult` produces both data files and returns the
tree, the ancestors, the event rows and geocoding stats.

Two things worth knowing:

**The geocoder is injected, not edited in.** `gedcom_cleaner` does
`from gedcom_geocoder import get_coords`, which binds the name at import time, so
patching the module attribute would not work. `build_master_csv` sets
`gedcom_cleaner.get_coords` directly. The cleaner's logic is untouched; it just
gets a faster geocoder underneath.

**`load_address_overrides` accepts two column layouts.** The original expects
`original_place, clean_address, lat, lon`; the real exported file carries
`Name, Value.lat, Value.lon, Value.address`. Under the original loader every row
produced an empty key and was dropped, so 273 manual corrections were silently
discarded. The cleaner takes this dictionary as a parameter, so the fix lives
here rather than in ported code.

---

## `reports/`

### The contract

Every report — regardless of where its logic came from — is a `Report` object:

```python
REPORT = Report(
    id="locations",
    title="Locations",
    description="...",          # written for a user, not a developer
    run=run,                    # (RunSpec) -> list[Artifact]
    params=[P_MAX_GENS, P_YEAR_MIN, P_YEAR_MAX],
    needs_events=True,          # wants events.csv
    needs_master_csv=False,     # wants master_tree.csv
    needs_target=True,          # is a focus person meaningful?
    requires=["..."],           # other reports to run first
    order=20,                   # UI ordering
)
```

`RunSpec` carries the GEDCOM path, target, output directory, merged parameters
and the `PipelineResult`. `spec.p(key, default)` reads a parameter, treating
empty string as absent.

`Artifact` is one output file plus how the results page should present it —
`kind` is `html`/`csv`/`pdf`/`json`, and `primary` marks the one to lead with.

### Adding a report

1. Write `reports/r_yourthing.py` exposing `REPORT`.
2. Add it to `ALL_REPORTS` in `reports/registry.py`.

Done — it appears in the UI with its parameters, and the runner works out which
data files to build. No UI edits.

### `registry.resolve_selection(ids)`

Expands a selection to include prerequisites. Picking the map implicitly picks
Locations, because the map deep-links into it.

> The result **must not be re-sorted afterwards**. `add()` appends prerequisites
> before their dependents; sorting the output by `order` could place a report
> ahead of the one it reads from. That is how the map would end up linking into
> a Locations report that had not been written yet.

### `theme.py` — one visual language

All HTML reports go through `page()` / `write_page()` and take colours from here.
This is what makes eight reports read as one product.

The categorical palette is validated for colour-vision deficiency and for
contrast in both light and dark mode. **Do not substitute ad-hoc hex values.**
Map markers use only the first three slots, which additionally clear the
all-pairs separation gate needed when marks sit next to each other arbitrarily.
Colour is never the only signal — every coloured element carries a text label.

### `tabular.py` — CSV as a first-class view

Turns any CSV into a styled table with sticky headers, click-to-sort and a live
filter. Four reports emit CSV natively; without this they would look like raw
dumps beside the HTML reports, and the product would visibly feel like two
systems. The CSV is still produced and still downloadable.

### Cross-report links

`r_locations.py` writes `place_anchors.json` — `{PlaceKey: anchor_id}` — into its
output directory. `r_map.py` reads it to build
`../locations/locations.html#<anchor>` links.

> This file exists because anchors get **de-duplicated**. `place_anchor()`
> sanitises spaces and hyphens identically, so `St-Constant` and `St Constant`
> collide, and the second gets a numbered suffix. The map cannot recompute that
> and must not guess — guessing produces silently dead links.

If Locations was not run, the map disables the links and says so rather than
rendering broken ones.

---

## `app/`

`server.py` is a small Flask app on `127.0.0.1:5333`.

| Route | Purpose |
|---|---|
| `GET /api/reports` | registry, for rendering the UI |
| `GET /api/browse` | directory listing, including Windows drive letters |
| `GET /api/tree/summary` | counts + the default focus person |
| `GET /api/people?q=` | person search |
| `GET /api/preview` | ancestor count at a given depth, live |
| `POST /api/run` | start a job, returns a job id |
| `GET /api/job/<id>` | poll state, log lines, artifacts |
| `GET /runs/<id>/<path>` | serve a generated file |

Runs execute on a background thread and are polled. The parsed tree is cached by
path **and mtime**, so editing the GEDCOM invalidates it.

**One report failing does not abandon the run.** Each is wrapped; the error and a
truncated traceback attach to that report and the rest continue.

The default focus person is resolved by name then birth year, and can be pinned
permanently by writing `default_target_id` to `data/config.json`.

`index.html` is the whole UI — plain HTML, CSS and JavaScript, no build step and
no dependencies. Editing it means editing one file.

---

## Testing it

There is no test suite; verification was done against the real file. To repeat it:

```python
import sys; sys.path.insert(0, '.')
from pathlib import Path
from core.pipeline import run_pipeline

r = run_pipeline(
    gedcom_path=Path("your.ged"),
    target_id="@I_1187810445@",
    data_dir=Path("data"), out_dir=Path("/tmp/out"),
    max_generations=6, use_network=False,   # offline = fast, US-only
)
print(len(r.ancestors), "ancestors,", len(r.event_rows), "events")
```

Worth re-checking after any change to place handling:

- coordinates fall inside the country they claim
- every map anchor resolves to a card in Locations
- `resolve_selection(["map"])` still returns `["locations", "map"]` in that order
- `load_address_overrides` still returns 273, not 0

---

## Things that will bite

**Offline mode is US-only.** The offline gazetteer covers US towns and counties.
With online lookup unchecked, foreign places get no coordinates and vanish from
the map. They still appear in Timelines and Locations.

**Nominatim is rate-limited** to roughly one request per second, by policy, not
by us. A cold cache on a large tree takes a while. It is a one-time cost and the
cache is committed to the repo, so most of it is already paid.

**The `Birt`/`Birth` spelling split** in `master_tree.csv` is inherited. Several
ported readers accept both defensively. Do not "tidy" it.

**Flat imports.** The ported modules do `from gedcom_parser import ...`, not
package-relative imports. `core/` and `reports/` are put on `sys.path` to keep
them running verbatim. That is deliberate; changing it means editing their code.
