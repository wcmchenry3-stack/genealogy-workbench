# Genealogy Workbench

A local web app for running genealogy reports against a GEDCOM file. Pick a family
file, choose who to centre it on, tick the reports you want, and get back maps,
timelines, charts and data-quality checks.

Everything runs on your own machine. Nothing about your family is uploaded
anywhere — the only network calls are geocoding lookups for places that aren't
already cached, and map tiles when you open the map.

---

## Getting started

**Windows** — double-click **`run.bat`**.

**macOS / Linux** — run **`./run.sh`**.

The first launch builds a private Python environment and installs dependencies,
which takes a minute or two. After that it starts in a few seconds. Your browser
opens automatically at <http://127.0.0.1:5333/>.

You need Python 3.10 or newer. On Windows, install it from
[python.org](https://www.python.org/downloads/) and make sure **"Add Python to
PATH"** is ticked during setup.

To stop the app, close the console window or press `Ctrl+C`.

---

## Using it

1. **Family file** — browse to a `.ged` file anywhere on your computer.
2. **Focus person** — search by name and pick someone. The app pre-selects a
   default; change it whenever you like.
3. **Scope** — how many generations back, and an optional year range. The app
   shows you live how many ancestors a given depth actually yields.
4. **Reports** — tick any combination. Some reports pull in others they depend
   on; the app says so rather than leaving you to remember.

Results appear as links you can open in a new tab. Everything is also written to
`runs/<timestamp>/` so nothing is lost when you close the browser.

---

## The reports

| Report | What it tells you |
|---|---|
| **Ancestor Timelines** | Every ancestor with their locations in date order, on a shared time axis so generations are comparable at a glance. |
| **Locations** | The same events organised by place — one card per town, with cemetery detail and a roster of who was there and when. Ranked to put the best research stops first. |
| **Research map** | Every located event on a worldwide map, filterable by family line, country, person and date. Click a marker to jump to that place's full entry in Locations. |
| **Ancestor Chart** | A printable pedigree chart, four generations per page, with page-to-page links where a branch runs deeper than fits. |
| **Immigrant Ancestors** | For each branch, the first ancestor born outside the United States — when and where each line arrived. |
| **Spouse Relationships** | Couples in the tree who share a blood ancestor. Common in older trees and easy to miss by eye. |
| **Relationship Diagnostics** | Parent/child links that look implausible — a parent too young, a parent who died before the birth, a birthplace impossibly far from a parent's. Catches data-entry errors. |
| **Possible Duplicate People** | Pairs who are probably the same person entered twice, ranked by confidence. |

---

## How it fits together

```
your .ged file
      │
      ▼
  core/  ── one parser, one place resolver, one geocoder
      │
      ├──► master_tree.csv   one row per person   (chart, immigrants, spouses,
      │                                            diagnostics, duplicates)
      └──► events.csv        one row per event    (timelines, locations, map)
                                                        │
                                                        ▼
                                            runs/<timestamp>/reports/…
```

Two data files because they answer different questions. `master_tree.csv` is the
person-level view — who someone was, when they were born and died. `events.csv`
is the event-level view — everywhere a person turns up, including residences and
census records, which is what the location-based reports need.

### Adding a report

Write a module in `reports/` exposing a `REPORT = Report(...)` object and list it
in `reports/registry.py`. It shows up in the UI automatically, with its
parameters, and the runner works out which data files it needs. See
`reports/base.py` for the contract.

### Further reading

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — how the code works, module by
  module: the data contracts, the report registry, the geocoding tiers, and the
  handful of places that will bite you if you change them carelessly.
- **[docs/PROJECT-HISTORY.md](docs/PROJECT-HISTORY.md)** — what was built and why,
  the decisions and their reasoning, the bugs found along the way, and what was
  and wasn't verified.

---

## Place lookup

Turning `"Cleveland, Cuyahoga, Ohio"` into coordinates happens in three tiers,
cheapest first:

1. **`data/location_library.json`** — the cache. Instant. It grows with every run
   and is never asked the same question twice.
2. **Offline gazetteer** — instant, no network, covers most US towns and counties
   at town-centre accuracy.
3. **[Nominatim](https://nominatim.org/)** — OpenStreetMap's geocoder. Worldwide,
   but rate-limited to about one request per second, so it goes last.

Unchecking *"Look up unknown places online"* in Step 3 skips tier 3. That's fine
for a US-only tree, but places outside the US will not appear on the map, because
the offline gazetteer only covers the United States.

Map pins report their own accuracy. A pin placed at a county centroid says so —
confirm the exact address before driving anywhere.

`data/address_override.csv` lets you correct a place by hand; it wins over all
three tiers.

---

## Your data stays yours

`.gitignore` deliberately excludes `.ged` files, `master_tree.csv`, `events.csv`
and everything under `runs/`. Family data is never committed, even by accident.

---

## Troubleshooting

**"Python was not found"** — install Python 3.10+ from python.org with "Add
Python to PATH" ticked, then run `run.bat` again.

**Port already in use** — set a different one: `set GW_PORT=5555` before running
(`GW_PORT=5555 ./run.sh` on macOS/Linux).

**The map is empty or missing foreign places** — either online lookup was
unchecked, or the geocoder couldn't reach Nominatim. The run log names how many
places failed to resolve.

**A report failed but others worked** — that's by design; one report failing
doesn't abandon the run. The error and traceback appear under that report in the
results.

**Starting over** — delete `.venv/` and run the launcher again.
