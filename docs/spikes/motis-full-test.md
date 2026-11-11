# MOTIS full Tri-City test — 2026-11-11

Environment: macOS arm64 (Apple Silicon), MOTIS v2.11.4, osmium 1.19.1.
Work dir: `/private/var/folders/2y/1bsn02s15h10sbtw8y9cfpk00000gn/T/opencode/motis-full`
Main repo `/Users/yan/Documents/bikerouter` was not modified.

## TL;DR

- `motis import`: **3.52 s**, **842.4 MB peak RSS** (803.4 MiB), 151 MB data dir.
- `motis server`: **107.5 MB idle**, **175.1 MB after first queries**, **175.2 MB after 25 more queries** (stable).
- Transit, local transit, bike, walk, bike+transit, and MEVO GBFS routing all worked.
- Gdańsk GTFS-RT worked: **250/250 entities matched (100%)**, `realTime: true`, scheduled vs. actual times differ.
- Main data gap: **Gdańsk GTFS expires 2026-11-25**, so the 30-day timetable loses all Gdańsk bus/tram after that date. Gdynia, SKM, and Polregio cover the requested window.

## Inputs and exact URLs

| Input | URL / source | Notes |
|---|---|---|
| MOTIS | `https://github.com/motis-project/motis/releases/download/v2.11.4/motis-macos-arm64.tar.bz2` | binary copied from the spike dir, v2.11.4 |
| OSM | `https://download.geofabrik.de/europe/poland/pomorskie-latest.osm.pbf` | timestamp `2026-11-08T21:21:00Z`, 118,459,502 B |
| Gdańsk GTFS | `https://ckan.multimediagdansk.pl/dataset/c24aa637-3619-4dc2-a171-a23eec8f2172/resource/30e783e4-2bec-4a7d-bb22-ee3e3b26ca96/download/gtfsgoogle.zip` | CKAN resource, last modified `2026-11-11T01:55:36Z`, 27,057,210 B |
| Gdynia GTFS | `https://api.zdiz.gdynia.pl/pt/gtfs.zip` | last modified `2026-11-11T04:10:07Z`, 18,350,361 B |
| SKM GTFS | `https://www.skm.pkp.pl/gtfs-mi-kpd.zip` | current official feed, 15,258,598 B |
| Polregio GTFS | `https://mkuran.pl/gtfs/polish_trains.zip` | unified Polish trains feed, agency `PR` extracted; 26,457,706 B |
| GTFS-RT | `https://ckan2.multimediagdansk.pl/gtfs-rt?feed=tripUpdates` | HTTP 301 → HTTPS; 77,911 B protobuf |
| MEVO GBFS | `https://gbfs.urbansharing.com/rowermevo.pl/gbfs.json` | requires `Client-Identifier` header |

The old `https://mevo-middleware.fly.dev/...` host no longer resolves (`Could not resolve host`). The official MEVO GBFS endpoint above works.

## Commands used

```sh
T=/private/var/folders/2y/1bsn02s15h10sbtw8y9cfpk00000gn/T/opencode/motis-full
cd "$T"

curl -fL -o gtfs-gdansk-current.zip \
  'https://ckan.multimediagdansk.pl/dataset/c24aa637-3619-4dc2-a171-a23eec8f2172/resource/30e783e4-2bec-4a7d-bb22-ee3e3b26ca96/download/gtfsgoogle.zip'
curl -fL -o gtfs-gdynia-current.zip 'https://api.zdiz.gdynia.pl/pt/gtfs.zip'
curl -fL -o gtfs-skm-current.zip 'https://www.skm.pkp.pl/gtfs-mi-kpd.zip'
curl -fL -o polish-trains.zip 'https://mkuran.pl/gtfs/polish_trains.zip'
python3 extract_polregio.py polish-trains.zip gtfs-polregio-current.zip
python3 trim_gtfs.py gtfs-gdansk-current.zip gtfs-gdansk-trimmed.zip
python3 trim_gtfs.py gtfs-gdynia-current.zip gtfs-gdynia-trimmed.zip
python3 trim_gtfs.py gtfs-skm-current.zip gtfs-skm-trimmed.zip
python3 trim_gtfs.py gtfs-polregio-current.zip gtfs-polregio-trimmed.zip

cd data
../motis config ../tricity.osm.pbf ../gtfs-gdansk-trimmed.zip \
  ../gtfs-gdynia-trimmed.zip ../gtfs-skm-trimmed.zip ../gtfs-polregio-trimmed.zip
# edit config.yml (num_days 30, first_day TODAY, no tiles/geocoding/railviz, add RT + GBFS)
/usr/bin/time -l ../motis import -d motis-data
../motis server -d motis-data
```

Example query:

```sh
curl 'http://localhost:8080/api/v6/plan?fromPlace=54.355,18.644&toPlace=54.518,18.531&time=2026-11-11T14:10:00%2B01:00&numItineraries=3'
```

## OSM extract

```sh
osmium extract --bbox 18.35,54.25,18.75,54.55 --overwrite \
  -o tricity.osm.pbf pomorskie-latest.osm.pbf
```

- `tricity.osm.pbf`: 30,096,243 B (28.7 MiB)
- 2,833,905 nodes, 419,401 ways, 4,074 relations
- Data timestamp: `2026-11-08T20:44:44Z`
- Header bbox is larger than requested (`14.815,53.451,20.347,58.916`) because `osmium extract` defaults to `complete_ways` and keeps long ferry/road ways. Tri-City data is present and routing worked.

## GTFS validity and trimming

`trim_gtfs.py` from the GraphHopper spike was copied to the work dir and used unchanged. It works, but Gdańsk/SKM barely shrink because their stops are mostly inside the bbox and `shapes.txt` dominates.

| Feed | Raw validity | Raw size | Trimmed size | Stops | Trips | Stop times | Active trips 2026-11-11 | Window coverage |
|---|---|---:|---:|---:|---:|---:|---:|---|
| Gdańsk | 2026-11-11..2026-11-25 | 27.1 MB | 26.9 MB | 1,511 | 92,265 | 2,152,650 | 4,283 | **15/31 days** |
| Gdynia | 2026-11-11..2027-01-20 | 18.4 MB | 5.1 MB | 766 | 9,648 | 191,824 | 2,005 | 31/31 days |
| SKM | 2026-10-19..2026-12-12 | 15.3 MB | 15.1 MB | 40 | 1,446 | 28,837 | 118 | 31/31 days |
| Polregio | 2026-11-10..2026-12-11 | 6.1 MB | 0.4 MB | 98 | 971 | 7,057 | 340 | 31/31 days |

Notes:
- Gdańsk is a short-horizon rolling feed, 15 days inclusive (`feed_info.end_date=20261125`). It cannot cover a full 30-day timetable. A local Gdańsk transit query on 2026-12-01 returns only a direct walk.
- Gdynia and SKM old zips were expired; both were replaced with current official feeds.
- The old Polregio zip was actually valid through 2026-12-12, but a current Polregio-only official feed was not found. The `PR` agency subset of `mkuran.pl/gtfs/polish_trains.zip` was used instead; it is valid through 2026-12-11.
- `trim_gtfs.py` renumbers `stop_sequence` and keeps the longest contiguous run of in-bbox stops, so times stay monotonic. MOTIS imported the trimmed feeds without errors.

## MOTIS config

Path: `data/config.yml`. Key settings:

```yaml
osm: ../tricity.osm.pbf
timetable:
  first_day: TODAY          # resolved to 2026-11-11
  num_days: 30
  railviz: false
  with_shapes: true
  link_stop_distance: 100
  max_footpath_length: 15
  max_matching_distance: 25
  preprocess_max_matching_distance: 250
  datasets:
    gtfs-gdansk-trimmed:
      path: ../gtfs-gdansk-trimmed.zip
      rt:
        - url: https://ckan2.multimediagdansk.pl/gtfs-rt?feed=tripUpdates
          protocol: gtfsrt
    gtfs-gdynia-trimmed:
      path: ../gtfs-gdynia-trimmed.zip
    gtfs-polregio-trimmed:
      path: ../gtfs-polregio-trimmed.zip
    gtfs-skm-trimmed:
      path: ../gtfs-skm-trimmed.zip
street_routing: true
osr_footpath: false
geocoding: false
reverse_geocoding: false
elevators: false
gbfs:
  feeds:
    mevo:
      url: https://gbfs.urbansharing.com/rowermevo.pl/gbfs.json
      headers:
        Client-Identifier: bikerouter-motis-test
```

There is no `tiles:` block. `geocoding`, `reverse_geocoding`, and `railviz` are disabled.

## Import

```sh
cd data
/usr/bin/time -l ../motis import -d motis-data
```

- real **3.52 s**, user 7.79 s, sys 0.31 s
- maximum resident set size **842,383,360 B = 842.4 MB = 803.4 MiB**
- peak memory footprint **706,020,504 B = 706.0 MB = 673.3 MiB**
- data dir **154,972 KB = 151.3 MiB**
- 2,424 locations total; no import errors or warnings
- RT was not fetched during import (it is fetched by the server)

For comparison, the earlier spike with the March 2026 OSM and four untrimmed feeds imported in 4.13 s at 792.6 MB peak. The current run is slightly heavier because the OSM extract is newer/larger and the current feeds have more data.

## Server memory

```sh
../motis server -d motis-data
```

- PID 54083, listening on `0.0.0.0:8080`, `n_threads=10`
- idle RSS: **107,488 KB = 107.5 MB = 105.0 MiB**
- after first route queries: **175,072 KB = 175.1 MB = 171.0 MiB**
- after 25 additional queries: **175,232 KB = 175.2 MB = 171.1 MiB**
- RSS is stable after warm-up; no per-query growth observed.
- The test server was stopped after the measurements; restart with `cd data && ../motis server -d motis-data`.

First RT/GBFS update completed about 2 s after the server started listening. RT refresh runs every 60 s and reports:

```text
GTFS-RT update stats for tag=gtfs-gdansk-trimmed:
total_entities=250, total_entities_success=250 (100%)
```

## Route results

All route queries in this section used `time=2026-11-11T14:10:00+01:00` (URL-encoded `%2B01:00`) and returned HTTP 200. Coordinates:

- Gdańsk Główny: `54.355,18.644`
- Gdynia Główna: `54.518,18.531`
- Plac Solidarności: `54.3605,18.6495`
- Sopot: `54.4415,18.5605`

| Query | HTTP | Result |
|---|---:|---|
| Transit Gdańsk Główny → Gdynia Główna | 200 | 3 itineraries. Fastest **2,340 s (39 min)**, 1 transfer: WALK → Polregio REG 1,260 s → WALK → BUS 204 120 s → WALK. Direct SKM options **2,820 s (47 min)**, 0 transfers. |
| Local transit Gdańsk Główny → Plac Solidarności | 200 | 7 itineraries. Fastest **540 s (9 min)**: WALK → TRAM 8 120 s → WALK. Typical **600 s (10 min)**: WALK → TRAM 3 180 s → WALK. Also BUS 289/186/123 options. |
| Bike Gdańsk Główny → Sopot | 200 | 1 direct BIKE itinerary, **2,954 s (49 min)**, **12,447 m**. |
| Walk short Gdańsk Główny → Plac Solidarności | 200 | 1 direct WALK itinerary, **745 s (12.4 min)**, **893 m**. |
| Walk medium Gdańsk Główny → Sopot | 200 | 1 direct WALK itinerary, **9,946 s (2 h 46 min)**, **11,983 m**. |
| Bike + transit Gdańsk Główny → Gdynia Główna | 200 | 3 itineraries, **1,740–2,280 s**. BIKE access → SKM/Polregio → BIKE egress. No bike-carriage leg is shown; the feeds default `bikes_allowed=false`, so the bike is used to/from the station. |
| MEVO direct Gdańsk Główny → Sopot | 200 | 4 direct RENTAL options, **3,185–3,408 s**, ~12.2 km. Provider `mevo`, form factor `BICYCLE`, e-bike vehicles available. |
| MEVO + transit Gdańsk Główny → Gdynia Główna | 200 | 3 itineraries, **2,040–2,700 s**. WALK → SKM/Polregio → WALK → RENTAL MEVO egress. |

Mode parameters used:

```text
transit:        (defaults)
local transit:  directModes=WALK&transitModes=TRANSIT
bike:           directModes=BIKE&transitModes=&maxMatchingDistance=250&maxDirectTime=7200
walk short:     directModes=WALK&transitModes=
walk medium:    directModes=WALK&transitModes=&maxDirectTime=14400
bike+transit:   directModes=BIKE&transitModes=TRANSIT&preTransitModes=BIKE&postTransitModes=BIKE&maxMatchingDistance=250
MEVO direct:    directModes=RENTAL&transitModes=&directRentalFormFactors=BICYCLE&maxMatchingDistance=250&maxDirectTime=7200
MEVO+transit:   directModes=RENTAL&transitModes=TRANSIT&preTransitModes=RENTAL&postTransitModes=RENTAL&directRentalFormFactors=BICYCLE&preTransitRentalFormFactors=BICYCLE&postTransitRentalFormFactors=BICYCLE&maxMatchingDistance=250
```

Bike queries used `maxMatchingDistance=250`; the server config default is 25, which can produce 0 direct bike results near pedestrian zones.

Example transit itinerary (fastest):

```text
2,340 s, 1 transfer
WALK 180 s  START -> Gdańsk Główny
REG  1,260 s Gdańsk Główny 14:39 -> Gdynia Główna 15:00  (Polregio)
WALK 120 s  Gdynia Główna -> Gdynia Dworzec Gł. PKP - Morska 01
BUS  120 s  Morska 01 -> Hala 03  (line 204)
WALK 660 s  Hala 03 -> END
```

Example direct SKM itinerary:

```text
2,820 s, 0 transfers
WALK 180 s  START -> GDAŃSK GŁÓWNY
SKM  2,040 s GDAŃSK GŁÓWNY 14:23 -> GDYNIA GŁÓWNA 14:57
WALK 600 s  GDYNIA GŁÓWNA -> END
```

## Real-time behaviour

The Gdańsk RT feed was fetched successfully (HTTP 200 after redirect) and MOTIS matched every entity. Parsed feed: 250 entities, 2,902 stop-time updates, arrival-delay range **−439 s .. +6,362 s**, average **+19.3 s**.

MOTIS marks RT data in the JSON:

- `leg.realTime: true`
- `leg.scheduledStartTime` / `scheduledEndTime` vs. adjusted `startTime` / `endTime`
- `place.arrivalTimestampReason: "PREDICTED"` / `"PROPAGATED"`

Example at `Dworzec Główny 01` (stop `gtfs-gdansk-trimmed_2001`):

| Route | Scheduled departure | Actual departure | RT delay at stop | Marking |
|---|---|---:|---:|---|
| TRAM 3 | 13:15:00Z | 13:14:00Z | −95 s | `realTime: true`, `PROPAGATED` |
| TRAM 10 | 13:20:00Z | 13:17:00Z | −180 s | `realTime: true`, `PROPAGATED` |
| TRAM 8 | 13:26:00Z | 13:26:00Z | 0 s | `realTime: true`, `PROPAGATED` |

Without RT (SKM stop `gtfs-skm-trimmed_7500`):

| Route | Scheduled | Actual | Marking |
|---|---|---:|---|
| SKM | 13:23:00Z | 13:23:00Z | `realTime: false`, `NO_RT_DATA` |

MOTIS does not expose a separate numeric `delay` field in these responses; it adjusts the timestamps and sets `realTime` plus the timestamp-reason fields. The adjusted times are enough to show the delay. RT is configured only for the Gdańsk feed; SKM, Gdynia, and Polregio have no RT in this test.

## GBFS / MEVO

The old `mevo-middleware.fly.dev` host is dead. The official GBFS endpoint is:

```text
https://gbfs.urbansharing.com/rowermevo.pl/gbfs.json
```

It requires a `Client-Identifier` header. MOTIS supports per-feed headers, so this works directly in `config.yml`.

Raw feed at test time:

- 875 stations
- 3,804 vehicles available (2,692 e-bikes)
- 7,713 docks available

MOTIS `/api/v1/rentals?point=54.355,18.644&radius=2000&providers=mevo` returned 78 stations and 54 vehicles within 2 km of Gdańsk Główny, provider group `MEVO`, form factor `BICYCLE`.

Routing results:
- Direct `RENTAL` query found 4 MEVO options for Gdańsk Główny → Sopot, 3,185–3,408 s, ~12.2 km, with `rental.providerId="mevo"` and `rental.systemName="MEVO"`.
- `preTransitModes=RENTAL` / `postTransitModes=RENTAL` produced a MEVO egress leg from Gdynia Główna, so sharing + transit is supported.

## Data-quality issues and blockers

1. **Gdańsk GTFS coverage is the main gap.** The feed is valid only 2026-11-11..2026-11-25 (15 days). With `num_days: 30`, Gdańsk tram/bus service disappears after 2026-11-25. A local query on 2026-12-01 returned only a direct walk; long-distance transit still worked via SKM/Polregio/Gdynia. `extend_calendar: true` could paper over this, but it would fabricate service and was not used.
2. **No current Polregio-only official GTFS found.** The `polregio.pl` page had no GTFS link. The current `PR` subset of `mkuran.pl/gtfs/polish_trains.zip` was used; it is valid through 2026-12-11. If a first-party Polregio feed is required, this is a sourcing gap.
3. **Old Gdynia/SKM feeds were expired.** Replaced with current official feeds; no remaining validity gap for those two.
4. **MEVO endpoint changed.** `mevo-middleware.fly.dev` no longer resolves. Use `gbfs.urbansharing.com/rowermevo.pl` with the required header.
5. **OSM header bbox is larger than requested.** `osmium extract` keeps complete ways, so the file header reports a wider bbox including long ferry/road ways. Tri-City data is present; this is not a routing problem.
6. **RT only covers Gdańsk.** Gdynia, SKM, and Polregio have no RT configured. SKM has a community GTFS-RT feed (`gtfs.kasznia.net/rt/skmt.pb`) but it is marked deprecated and was not tested.
7. **RT delay quality varies.** The Gdańsk feed contained delays from −439 s to +6,362 s, including some large positive outliers. This is upstream data quality, not a MOTIS issue.
8. **`trim_gtfs.py` copies `transfers.txt` unchanged.** For Polregio this can leave references to stops removed by trimming. MOTIS imported without errors, but a stricter GTFS validator may complain.

## Recommendation

MOTIS handles the betterdojade Tri-City use case comfortably on this machine:

- import peak **< 1 GB** and **~3.5 s**;
- server **~107 MB idle**, **~175 MB warm**, stable under repeated queries;
- transit, local transit, bike, walk, bike+transit, and MEVO sharing all return useful itineraries;
- Gdańsk RT is applied and clearly marked.

The main production risk is data freshness, not engine capability: the Gdańsk feed must be refreshed at least every 14 days, and a 30-day timetable will have a hard local-transit gap after 2026-11-25. A production setup should either refresh Gdańsk GTFS frequently or limit `num_days` to the feed horizon and handle the gap explicitly.

## Artifacts

All under `/private/var/folders/2y/1bsn02s15h10sbtw8y9cfpk00000gn/T/opencode/motis-full`:

- `REPORT.md` — this report
- `extract_polregio.py`, `trim_gtfs.py` — feed preparation scripts
- `data/config.yml` — MOTIS config
- `import.log`, `server.log` — import/server logs
- `transit-gdansk-gdynia.json`, `transit-local.json` — transit results
- `transit-local-dec.json`, `transit-long-dec.json` — 2026-12-01 coverage-gap evidence
- `walk-short.json`, `walk-medium.json`, `bike-sopot.json` — direct results
- `multimodal-bike.json`, `multimodal-mevo.json`, `mevo-direct.json` — multimodal/GBFS results
- `stoptimes.json`, `stoptimes-skm.json` — RT comparison
- `rentals.json` — MOTIS rental/stations response
- `trip-updates.pb`, `trip-updates.json` — raw and decoded GTFS-RT
- `mevo-station-status.json`, `mevo-station-info.json` — raw MEVO GBFS
- `tricity.osm.pbf`, `gtfs-*-trimmed.zip` — inputs used by MOTIS
