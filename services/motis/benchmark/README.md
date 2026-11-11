# Bike-route benchmark

Compares MOTIS, GraphHopper, and BRouter on 15 Tri-City origin and
destination pairs. The recorded snapshot is from 2026-11-11 and is kept in
`manifest.json`; the scripts can reproduce the comparison on another setup.

## Files

| File | Purpose |
|---|---|
| `bench.py` | Queries MOTIS, GraphHopper, and BRouter; writes raw responses to `out/` and updates `manifest.json` |
| `metrics.py` | Computes distance, road class, surface, signal, crossing, turn, and overlap metrics; writes `metrics.json` |
| `points.json` | Canonical named coordinates used by `bench.py`; the same points are recorded in `manifest.json` |
| `manifest.json` | Recorded run: points, routes, engine status, and BRouter distances/times |

`out/`, `metrics.json`, `osm_index.pkl`, `highways.geojson`, and
`signals.geojson` are generated and not committed.

## Prerequisites

- MOTIS server with the Tri-City data on `http://127.0.0.1:8081`.
- GraphHopper server with a `bike` profile on `http://127.0.0.1:8989`.
- Network access to the public BRouter API.
- Python 3 with the standard library only.

The URLs can be overridden with `MOTIS_URL`, `GH_URL`, and `BROUTER_URL`.
MOTIS must be started with a separate port if the default 8080 is already
in use; the recorded run used `server.port: 8081` in the MOTIS config.

## Prepare the OSM index

`metrics.py` snaps MOTIS geometry to OSM ways and counts nearby signals and
crossings. Build the two GeoJSON inputs from the clipped OSM extract:

```sh
cd services/motis

osmium tags-filter data/tricity.osm.pbf w/highway \
  -o benchmark/highways.osm.pbf
osmium export benchmark/highways.osm.pbf \
  -f geojson -o benchmark/highways.geojson

osmium tags-filter data/tricity.osm.pbf \
  n/highway=traffic_signals,crossing -o benchmark/signals.osm.pbf
osmium export benchmark/signals.osm.pbf \
  -f geojson -o benchmark/signals.geojson
```

The first `metrics.py` run builds `osm_index.pkl` from `highways.geojson`
(about 42 MB for the Tri-City extract). Delete the pickle to rebuild the
index after changing the OSM data.

## Run

```sh
cd services/motis/benchmark

# Query all engines. This writes out/*.json and manifest.json.
python3 bench.py

# Compute metrics. This reads out/ and manifest.json.
python3 metrics.py
```

`bench.py` uses a fixed departure of `2026-11-11T12:00:00+01:00` and a
bike-only MOTIS query:

```text
directModes=BIKE
transitModes=
maxMatchingDistance=250
maxDirectTime=14400
```

Change the timestamp in `bench.py` for a different run. The MOTIS query is
retried once with `maxMatchingDistance=2000` only for diagnostics when the
strict query returns no direct route; the diagnostic response is stored
inside the raw JSON and does not change the primary result.

## Recorded result

All 15 routes returned a direct MOTIS bike itinerary. MOTIS was at or near
the shortest distance on 14 of 15 routes (median ratio to the best engine
1.00). The exception was Gdańsk Główny → Brzeźno: MOTIS was 52% longer
(11.24 km versus 7.38–8.10 km), with a roughly 4 km out-and-back loop along
the beach, 3.9 km (35%) unpaved, and 2.0 km of `surface=sand`.

| Engine | Total km | Speed | Cycle/path/track | Primary/secondary/trunk | Unpaved | Signals/km | Turns/km |
|---|---:|---:|---:|---:|---:|---:|---:|
| MOTIS bike | 128.1 | 15.1 km/h | 82% | 5% | 5% | 4.9 | 1.9 |
| GraphHopper bike | 128.9 | 16.5 km/h | 79% | 4% | 1% | 4.6 | 2.4 |
| BRouter trekking | 129.8 | 19.2 km/h | 79% | 2% | 3% | 4.3 | 2.0 |
| BRouter fastbike | 127.8 | 19.1 km/h | 39% | 31% | 0% | 4.6 | 1.8 |
| BRouter safety | 131.6 | 19.1 km/h | 82% | 1% | 3% | 4.3 | 2.1 |

Excluding the Brzeźno route, MOTIS is 80% cycle/path/track, 5% major, and
2.3% unpaved, close to BRouter trekking. Its gaps are surface weighting,
turn-by-turn instructions (all steps are `CONTINUE`), elevation, and an
explicit traffic-signal cost. Its ETA is about 8–12% slower than
GraphHopper.

The recorded `manifest.json` contains one failed BRouter request: the
`safety` profile returned HTTP 403 for r10 (Gdańsk Główny → Zaspa), likely
public-API rate limiting. Other engines completed that route.

## Metric definitions

- **Distance/duration:** reported by each engine.
- **Road class:** MOTIS percentages are estimated by snapping each segment
  midpoint to the nearest OSM `highway` within 30 m. GraphHopper uses its
  `road_class` details; BRouter uses `WayTags`. MOTIS values are approximate
  (±5–10 percentage points).
- **Major:** `trunk`, `primary`, `secondary`, and their links.
- **Unpaved:** `sand`, `ground`, `dirt`, `gravel`, `compacted`, `unpaved`,
  `grass`, `wood`, and similar values.
- **Signals/crossings:** OSM nodes within 25 m of the route, deduplicated.
- **Turns:** bearing changes above 32° with at least 18 m spacing. This is a
  geometric count, not a navigation instruction count.
- **Overlap:** percentage of MOTIS samples within 30 m of the BRouter
  trekking geometry.
- **Ascent:** BRouter only. MOTIS and the tested GraphHopper graph are 2D
  and return no elevation.

## Use in the app

MOTIS bike routing is usable for a demo but not production-grade navigation.
Keep it labeled beta and add guardrails for unpaved/sand segments and
pedestrian-only destinations. If turn-by-turn, elevation, or consistent
surface quality is required, use MOTIS for transit and BRouter for the bike
legs.
