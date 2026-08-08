# Genealogy Workbench — what we built and why

*August 2026*

This is the record of how this project came together: what was asked for, what
was decided, what the data turned out to be, and what went wrong along the way.
It exists so that in six months there is an answer to "why is it like this?"

---

## Part one: a research trip

The work started with a specific, practical question — not with software.

> *"I want to analyze the locations within Ohio and Michigan of Tammy Jo Stull's
> ancestors… I want to visit these places (cemeteries, genealogy centers) so I
> can further my research."*

The brief had three parts: trace her ancestors back until each line left
Ohio/Michigan, collect every place they lived and when, and produce three
reports — per-person timelines, per-location rosters, and a map.

### What the tracing rule actually meant

The stated rule was that a line stops at the first ancestor who was neither born
nor died in the target states. The subtlety, clarified partway through, was
**which** person that meant:

> *"If this is the person who made the migration to Ohio, then yes count them.
> If this is that person's parent who stayed behind, do not count them."*

That distinction is the whole rule. Someone born in Bohemia who died in Cleveland
is the migrant and belongs in the data; their parents, who lived and died in
Bohemia, do not. Keeping anyone with a birth *or* death in the target states
captures exactly that boundary.

West Virginia was added mid-flight, which turned out to matter — the Marsh family
of Wheeling is a genuine branch, not a stray.

### What the data said

| | |
|---|---|
| Ancestors in scope | 47 across 8 generations |
| Located events | 279 |
| Distinct places | 62 |
| Ohio / West Virginia / Michigan | 261 / 14 / 4 events |

The best research stops, ranked by burials:

1. **Cleveland, Cuyahoga Co.** — 10 burials, 19 people, 1886–1959. Four named
   cemeteries with section and lot numbers: Lake View, Calvary, Highland Park,
   Harvard Grove.
2. **Drakesburg, Portage Co.** — 6 burials, no cemetery named anywhere in the
   file. The highest-value unknown on the list.
3. **Wheeling, Ohio Co., WV** — 4 burials.

Three findings were worth as much as the reports themselves:

- **Only 11 of 35 burials name a cemetery.** The rest record a town only. This
  was not an extraction failure — the names simply are not in the GEDCOM. It
  changes the trip: those need looking up before driving.
- **Michigan is a one-family detour.** Four events total. If more was expected,
  that points at the tree rather than the analysis.
- **"Ohio" is not always Ohio.** `Wheeling, Ohio, West Virginia` means Ohio
  *County*, West Virginia. A keyword match pulls it in wrongly. This trap
  recurred throughout and shaped how place parsing was built.

---

## Part two: turning it into a system

The second brief was operational:

> *"I want to take both sets of scripts (the ones we built and the ones in
> drive) and operationalize it… once we are done, we should not have any idea if
> a report comes from drive or the ones we created. It is one system, not two
> stitched together."*

### What was already there

The Google Drive side was 21 Python files built for Google Colab. The important
discovery was that **only two of them were actually Colab-bound**:

- `phase0_bootstrap.py` — mounted Drive and auto-converted `.ipynb` notebooks to
  `.py`. This machinery existed *only* because Colab forces notebooks. Off Colab
  it has no reason to exist.
- `main_controller.py` — hardcoded `/content/drive/MyDrive/Genealogy` and called
  `drive.mount()`.

Everything else was portable Python with clean public APIs. That made "rewrite
only what is necessary" achievable almost literally.

### The seam, and why it closed

Two systems existed because they had two data layers. The Drive reports read
`master_tree.csv` (one row per person). The new reports built their own
`data.json`. Anything built on top of that split would always feel like two
things bolted together.

The fix was one pipeline producing both:

- **`master_tree.csv`** keeps its exact 21-column schema. The five existing
  reports read it unchanged and never knew anything happened.
- **`events.csv`** is a new long-format companion — one row per person per dated
  place, carrying residence, census, burial and probate. The person-level schema
  simply cannot express "lived in Cleveland in 1910 and 1920"; that is a
  different shape, not a duplicate.

Then a **report registry**: every report declares an id, title, description,
parameters and outputs, and the UI renders itself from that list. There is no
"imported" section and no "new" section — there are eight reports.

The last piece was presentation. Four of the five ported reports emit CSV; the
new ones emit styled HTML. Left alone, that difference alone would have given
the game away. So the CSV reports now also render through a shared table view
with the same typography, colours and controls. The underlying CSV is still
produced and still downloadable — nothing was taken away.

### Decisions and their reasons

| Decision | Why |
|---|---|
| Local Flask app, launched by `run.bat` | The ask was "click a batch file, reports appear in the browser." No server, no accounts, no cloud. |
| Geographic pruning deleted entirely | It baked one report's filter into the shared data, which is exactly why the old design could not go worldwide. The walk now collects everything; reports filter their own view. |
| Cache → offline US gazetteer → Nominatim | Nearly half of the 3,843 distinct places are outside the US, so offline-only was off the table. The offline tier halves the one-time cold start (~27 min vs ~64 min) and keeps US-only runs off the network entirely. |
| Leaflet with OpenStreetMap tiles | The tree spans twelve countries. A bundled state-outline map cannot serve that, and street-level zoom matters for finding cemeteries. |
| Map deep-links into Locations | The reported complaint was that map detail did not render. The proposed fix — click a place, get its Locations entry — is better than the side panel it replaces, because Locations carries the fuller record anyway. |
| Private repo, family data gitignored | `.ged` files, `master_tree.csv`, `events.csv` and `runs/` never leave the machine. |

### The map problem, diagnosed

The original map *did* render detail — in a right-hand side panel that collapsed
below the map under about 860px. Viewed in a narrow window, clicking a pin sent
detail somewhere invisible. Rather than just widening a breakpoint, the fix took
the suggestion: markers now link straight into that town's card in the Locations
report. The inline panel stays for quick scanning.

This created a small contract problem worth recording. Locations de-duplicates
its HTML anchors, because this tree contains both `St-Constant` and
`St Constant`, which sanitise to the same string. The map cannot recompute those
suffixes, so Locations now publishes `place_anchors.json` and the map reads it.
Guessing would have produced silently dead links.

---

## Bugs found

Three real defects surfaced, none of them cosmetic.

**1. A wrongly excluded ancestor.** An independent audit — a second agent asked
to write its own parser from scratch and disagree — found that
**Michael Henry Welton** had been pruned as "born and died outside the target
states." He died in Steubenville, Ohio. The GEDCOM records it as:

```
2 PLAC Steubenville, Jefferson County  Ohio
```

Note the missing comma before "Ohio". A comma-splitting parser reads
`Jefferson County  Ohio` as one unrecognisable token, fails to find a state, and
concludes the death was elsewhere. Two fixes followed: split a trailing state
name out of the last token, and never treat an *unresolved* place as evidence of
absence. He is in the data now, and his line correctly ends at his Irish parents.

**2. Every event attributed to one person.** A stale loop variable in
`build_events_csv` meant every row in `events.csv` got the same `PersonID` —
whichever ancestor happened to be last in dictionary order. It collapsed 209
ancestors into one. Caught while building the timeline report, which is exactly
where it would look like the report was broken rather than the pipeline.

**3. 273 place corrections silently discarded.** `load_address_overrides`
expects columns `original_place, clean_address, lat, lon`. The actual
`address_override.csv` carries `Name, Value.lat, Value.lon, Value.address`. Every
row produced an empty key and was skipped, so the override dictionary was always
empty. **These manual corrections had never been applied to anything.** The new
loader accepts both layouts: 0 → 273.

---

## How it was verified

Correctness mattered more than usual here, because a wrong coordinate means
driving to the wrong cemetery.

- **An independent second implementation.** For the ancestor trace, a separate
  agent wrote its own GEDCOM parser and walker from scratch and compared results.
  It agreed on 78 of 79 individuals and found the Welton bug in the disagreement.
- **Spot-checks against the source.** Twelve extracted rows were traced back to
  the raw GEDCOM lines — dates, place strings, cemetery names, coordinates.
- **Coordinate sanity.** Every geocoded point was checked to fall inside the
  bounding box of the state it claimed.
- **Real UI testing.** The finished app was driven end to end in a headless
  browser: load a file, pick a person, run all eight reports, check the
  artifacts. Zero failures, zero console errors.
- **Link integrity.** All 147 map deep-links were confirmed to resolve to real
  anchors in the Locations report.

### What remains unverified

**The live Nominatim call.** The build environment could not reach it. The
network tier's plumbing was tested with a stub — query construction, cache
write-back, permanent-failure caching, rate limiting all confirmed — but the
real call is unproven until it runs on a machine with internet access. If it
fails, the run log reports how many places did not resolve rather than silently
producing an empty map.

---

## Where it ended up

| | |
|---|---|
| Python | 6,088 lines across 31 files |
| Ported unchanged | 2,827 lines |
| New | 3,261 lines |
| Reports | 8 |
| Files edited from the originals | **1** (`gedcom_visualizer.py`, 2 lines) |

Nine of the ten ported modules are byte-identical to what was in Drive. The
tenth lost a `get_ipython().system('pip install reportlab')` line that `nbconvert`
had translated literally out of a notebook cell.

Two files were dropped: `phase0_bootstrap.py` and `main_controller.py`.

Unbounded, the trace now reaches **1,955 ancestors across 31 generations** —
back to Robert I of Normandy.
