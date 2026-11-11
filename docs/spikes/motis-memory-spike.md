# MOTIS Tri-City memory spike — 2026-11-11

Environment: macOS 27.2 (26B123), arm64 (Apple Silicon), Homebrew 7.0.12.
Repo untouched. All work under:
`/private/var/folders/2y/1bsn02s15h10sbtw8y9cfpk00000gn/T/opencode/motis-spike`

## Versions / inputs

- MOTIS v2.11.4, `motis-macos-arm64.tar.bz2` (47,568,153 bytes), binary `Mach-O 64-bit executable arm64`, 50,969,400 bytes.
- osmium 1.19.1 (libosmium 2.23.1), installed with `brew install osmium-tool`.
- OSM source: `/Users/yan/Documents/graphhopper/pomorskie-latest.osm.pbf` (112,379,185 bytes).
- Extract: `tricity.osm.pbf`, 28,540,845 bytes (27.2 MiB), 2,697,894 nodes / 398,868 ways / 3,948 relations.
  - Requested bbox: `18.35,54.25,18.75,54.55`.
  - Header data bbox is larger (15.5677,53.4508,20.3469,58.9164) because `osmium extract` default `complete_ways` kept long ferry ways. Tricity data is present.
- GTFS:
  - Current Gdańsk: downloaded 2026-11-11 from CKAN `gtfsgoogle.zip`, 27,057,210 bytes. `calendar_dates.txt` 2026-11-11..2026-11-25; `feed_info.end_date=20261125`; valid for query date.
  - Old Gdańsk repo feed: `calendar_dates` 2026-03-19..2026-04-02; expired.
  - Gdynia: `calendar_dates` 2026-03-02..2026-05-06; expired.
  - SKM: `calendar` 2026-02-13..2026-06-13; expired.
  - Polregio: `calendar` 2025-12-14..2026-12-12; valid.

## Commands

```sh
T=/private/var/folders/2y/1bsn02s15h10sbtw8y9cfpk00000gn/T/opencode/motis-spike
mkdir -p "$T" && cd "$T"
curl -fL -o motis-macos-arm64.tar.bz2 \
  https://github.com/motis-project/motis/releases/download/v2.11.4/motis-macos-arm64.tar.bz2
tar xjf motis-macos-arm64.tar.bz2
./motis --help                      # MOTIS v2.11.4

brew install osmium-tool            # 1.19.1
osmium extract --bbox 18.35,54.25,18.75,54.55 \
  -o tricity.osm.pbf /Users/yan/Documents/graphhopper/pomorskie-latest.osm.pbf --overwrite

cd "$T/data"
../motis config ../tricity.osm.pbf ../gtfs-gdansk-current.zip \
  /Users/yan/Documents/graphhopper/gtfs-gdynia.zip \
  /Users/yan/Documents/graphhopper/gtfs-skm.zip \
  /Users/yan/Documents/graphhopper/gtfs-polregio.zip
# edit config.yml: remove tiles block, num_days 365 -> 30,
# geocoding/reverse_geocoding -> false, railviz -> false

/usr/bin/time -l ../motis import -d motis-data
nohup ../motis server -d motis-data > server.log 2>&1 & echo $! > server.pid
```

Second (local-GTFS-only) variant used `data2/` with Gdańsk current + Gdynia + SKM,
no Polregio, same edits.

## Config highlights

- `osm: ../tricity.osm.pbf`
- `timetable.first_day: TODAY` (2026-11-11), `num_days: 30`
- `timetable.with_shapes: true`, `adjust_footpaths: true`, `link_stop_distance: 100`,
  `max_footpath_length: 15`, `max_matching_distance: 25`,
  `preprocess_max_matching_distance: 250`
- `street_routing: true`, `osr_footpath: false`
- `geocoding: false`, `reverse_geocoding: false`, `elevators: false`
- tiles block removed (default was enabled with `db_size: 274877906944`)
- `railviz: false`
- Full config datasets: `gtfs-gdansk-current`, `gtfs-gdynia`, `gtfs-skm`, `gtfs-polregio`.

## Import results

`/usr/bin/time -l ../motis import -d motis-data`

### Full 4-feed config

- real 4.13 s, user 8.35 s, sys 0.26 s
- maximum resident set size: 792,641,536 bytes = 792.6 MB = 756 MiB
- peak memory footprint: 660,128,872 bytes = 660.1 MB
- data dir: 184 MB
- timetable metrics:
  - Gdańsk current: 2026-11-11..2026-11-26, 1,625 locations, 92,600 trips, 92,600 transportsXDays
  - Gdynia: 2206-04-11..2026-11-05, 1,149 locations, 9,495 trips, 0 transportsXDays
  - Polregio: 2026-11-09..2026-12-10, 5,481 locations, 47,699 trips, 66,722 transportsXDays
  - SKM: 2206-04-11..2026-11-05, 81 locations, 1,482 trips, 0 transportsXDays
  - Gdynia/SKM have no active service in the Nov 2026 window.

### Local-only config (no Polregio)

- real 3.66 s, user 7.52 s, sys 0.28 s
- maximum resident set size: 788,021,248 bytes = 788.0 MB = 751.5 MiB
- peak memory footprint: 656,049,280 bytes = 656.0 MB
- data dir: 171 MB
- Polregio adds ~4.6 MB peak RSS and ~13 MB on disk.

## Server RSS

macOS `ps -o rss=` reports KB.

### Full dataset (PID 45944)

- ready after 2 s; `n_threads=10`
- idle: 77,632 KB = 77.6 MB = 75.8 MiB
- after first transit query: 95,152 KB = 95.2 MB = 92.9 MiB
- after ~10 queries: 132,032 KB = 132.0 MB = 128.9 MiB

### Local-only dataset (PID 46962)

- ready after 2 s
- idle: 65,744 KB = 65.7 MB = 64.2 MiB
- after first transit query: 82,240 KB = 82.2 MB = 80.3 MiB
- after bike queries: 92,704 KB = 92.7 MB = 90.5 MiB

## Route queries

Timestamp must include a timezone offset. Bare local time is rejected:

```
GET /api/v6/plan?...&time=2026-11-11T12:00:00
HTTP 400 {"error":"parameter \"time\": failed to parse timestamp \"2026-11-11T12:00:00\""}
```

`2026-11-11T12:00:00+01:00` (URL-encoded `%2B01:00`) and `...Z` work. Epoch seconds rejected.
Both `/api/v1/plan` and `/api/v6/plan` exist; bundled UI uses v6.

### Full dataset, long transit route

```sh
curl -sS 'http://localhost:8080/api/v6/plan?fromPlace=54.355,18.644&toPlace=54.518,18.531&time=2026-11-11T12:00:00%2B01:00&numItineraries=3'
```

HTTP 200, 3 itineraries, 0 transfers each:

- 2220 s: WALK 240 s -> REGIONAL_RAIL 1380 s (Gdańsk Główny -> Gdynia Główna) -> WALK 600 s
- 2280 s: same with 1440 s rail
- 2220 s: same with 1380 s rail

`/api/v1/plan` with the same parameters also returned HTTP 200 and 3 itineraries.

### Local-only, short transit route

`fromPlace=54.355,18.644&toPlace=54.360,18.650`, `directModes=WALK&transitModes=TRANSIT`
HTTP 200, 6 itineraries + 1 direct walk; 600 s examples:
WALK -> TRAM/BUS (Dworzec Główny -> Plac Solidarności) -> WALK.

### Walking-only

`directModes=WALK&transitModes=` HTTP 200, 1 direct walk, 715 s.

### Bike

With server default `maxMatchingDistance=25`, direct bike returned 0.
With UI default `maxMatchingDistance=250` and `maxDirectTime=7200`, Gdańsk -> Sopot:

`directModes=BIKE&transitModes=&maxMatchingDistance=250&maxDirectTime=7200`
HTTP 200, 1 direct BIKE itinerary, 2911 s, 12,296 m.

A very short bike query still returned 0 even with 250; likely endpoint snapping in the pedestrian zone, not a general bike-profile failure.

## Blockers / caveats

- `osmium` was not installed; Homebrew install succeeded (no blocker).
- Docker unavailable; not needed.
- Gdynia and SKM feeds are expired for Nov 2026; old Gdańsk feed also expired.
  Current Gdańsk GTFS was downloaded successfully from CKAN and used.
- Long transit results come from the nationwide Polregio feed; Gdynia/SKM contribute 0 active trips.
- `motis config` defaults to 365 days and enables tiles/geocoding; both changed/removed.
- OSM extract header bbox is larger than requested due to complete-way/ferry inclusion.
- Bike short-route quirk noted above.

## Recommendation

MOTIS is substantially lighter than the stated GraphHopper 4–6 GB for this use case:

- import peak ~0.79 GB even with the nationwide Polregio feed;
- server idle ~0.07 GB, ~0.08–0.10 GB after typical queries, ~0.13 GB after many queries.

The OSM street graph dominates import peak; adding Polregio only added ~5 MB peak RSS.
This looks like a viable lighter replacement, with the caveats that the measurement is
macOS arm64, only 30 timetable days, no realtime, and GTFS quality/currency matters.
