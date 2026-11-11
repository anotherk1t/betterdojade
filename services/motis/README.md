# MOTIS routing service (Tri-City)

Starter artifacts for running MOTIS v2.11.4 with Gdańsk, Gdynia, SKM, and
Polregio GTFS feeds, OpenStreetMap street routing, Gdańsk GTFS-RT trip
updates, and the official MEVO GBFS feed.

This directory contains data-preparation scripts, a tested configuration
template, API examples, and the bike-route benchmark. It is a reference
setup, not an application integration.

## Contents

| Path | Purpose |
|---|---|
| `config.example.yml` | MOTIS configuration template; copy to `config.yml` |
| `trim_gtfs.py` | Clip a GTFS feed to the Tri-City bounding box |
| `extract_polregio.py` | Extract the `PR` agency from the Polish trains feed |
| `api-examples.md` | `/api/v6/plan` examples for transit, bike, walk, and bike + transit |
| `benchmark/` | MOTIS / GraphHopper / BRouter bike-route comparison |

## Data sources

URLs current at the time of the spike (2026-11-11). Re-check each source
before a production refresh.

| Input | URL | Notes |
|---|---|---|
| OSM | `https://download.geofabrik.de/europe/poland/pomorskie-latest.osm.pbf` | Pomorskie extract; clipped to Tri-City |
| Gdańsk GTFS | `https://ckan.multimediagdansk.pl/dataset/c24aa637-3619-4dc2-a171-a23eec8f2172/resource/30e783e4-2bec-4a7d-bb22-ee3e3b26ca96/download/gtfsgoogle.zip` | CKAN resource; rolling 15-day feed |
| Gdynia GTFS | `https://api.zdiz.gdynia.pl/pt/gtfs.zip` | ZDiZ Gdynia |
| SKM GTFS | `https://www.skm.pkp.pl/gtfs-mi-kpd.zip` | PKP SKM Tricity |
| Polregio GTFS | `https://mkuran.pl/gtfs/polish_trains.zip` | Unified Polish trains feed; agency `PR` extracted |
| Gdańsk GTFS-RT | `https://ckan2.multimediagdansk.pl/gtfs-rt?feed=tripUpdates` | GTFS-RT trip updates; protobuf |
| MEVO GBFS | `https://gbfs.urbansharing.com/rowermevo.pl/gbfs.json` | Official feed; requires `Client-Identifier` |
| MOTIS binary | `https://github.com/motis-project/motis/releases/download/v2.11.4/motis-macos-arm64.tar.bz2` | macOS arm64 build; use the matching release asset elsewhere |

### Feed validity at test time

| Feed | Validity | Size | Notes |
|---|---|---:|---|
| Gdańsk | 2026-11-11 .. 2026-11-25 | 27.1 MB | 15-day rolling feed; the main coverage risk |
| Gdynia | 2026-11-11 .. 2027-01-20 | 18.4 MB | Covers a 30-day timetable |
| SKM | 2026-10-19 .. 2026-12-12 | 15.3 MB | Covers a 30-day timetable |
| Polregio | 2026-11-10 .. 2026-12-11 | 6.1 MB | `PR` subset of the unified feed |

The Gdańsk feed only covers 15 days. With `num_days: 30`, Gdańsk bus and
tram service disappears after the feed end date, and local queries fall
back to walking. Refresh the feed at least every 14 days, or cap the
timetable horizon to the feed and show the coverage gap in the status page.
Do not enable `extend_calendar` just to fill the gap: it invents service.

### MEVO GBFS

The official endpoint replaces the old `mevo-middleware.fly.dev` host, which
no longer resolves. Every request needs a `Client-Identifier` header:

```sh
curl -H 'Client-Identifier: bikerouter-motis' \
  'https://gbfs.urbansharing.com/rowermevo.pl/gbfs.json'
```

MOTIS supports per-feed headers, so the identifier is set in
`config.example.yml`. Use a stable, descriptive value for the deployment.

### Gdańsk GTFS-RT

MOTIS polls `https://ckan2.multimediagdansk.pl/gtfs-rt?feed=tripUpdates`
while the server runs (`update_interval: 60`). The endpoint redirects HTTP
to HTTPS. GTFS-RT is configured only for the Gdańsk dataset; Gdynia, SKM,
and Polregio have no feed configured. In responses, adjusted times are
marked with `realTime: true`, `scheduledStartTime` / `scheduledEndTime`, and
`arrivalTimestampReason` / `departureTimestampReason`. Without a feed,
`realTime` is `false` and the reason is `NO_RT_DATA`.

## Build and import

Prerequisites: `osmium-tool`, Python 3, and the MOTIS binary on `PATH` (or
referenced as `./motis`).

```sh
cd services/motis
mkdir -p data/gtfs

# 1. OSM extract for the Tri-City area.
curl -fL -o data/pomorskie-latest.osm.pbf \
  'https://download.geofabrik.de/europe/poland/pomorskie-latest.osm.pbf'
osmium extract --bbox 18.35,54.25,18.75,54.55 --overwrite \
  -o data/tricity.osm.pbf data/pomorskie-latest.osm.pbf

# 2. GTFS feeds.
curl -fL -o data/gtfs/gdansk-current.zip \
  'https://ckan.multimediagdansk.pl/dataset/c24aa637-3619-4dc2-a171-a23eec8f2172/resource/30e783e4-2bec-4a7d-bb22-ee3e3b26ca96/download/gtfsgoogle.zip'
curl -fL -o data/gtfs/gdynia-current.zip 'https://api.zdiz.gdynia.pl/pt/gtfs.zip'
curl -fL -o data/gtfs/skm-current.zip 'https://www.skm.pkp.pl/gtfs-mi-kpd.zip'
curl -fL -o data/gtfs/polish-trains.zip 'https://mkuran.pl/gtfs/polish_trains.zip'

# 3. Polregio subset and Tri-City clipping.
python3 extract_polregio.py data/gtfs/polish-trains.zip data/gtfs/polregio-current.zip
python3 trim_gtfs.py data/gtfs/gdansk-current.zip data/gtfs/gdansk.zip
python3 trim_gtfs.py data/gtfs/gdynia-current.zip data/gtfs/gdynia.zip
python3 trim_gtfs.py data/gtfs/skm-current.zip data/gtfs/skm.zip
python3 trim_gtfs.py data/gtfs/polregio-current.zip data/gtfs/polregio.zip

# 4. Configuration.
cp config.example.yml config.yml

# 5. Import and serve.
motis import -d data/motis-data
motis server -d data/motis-data
```

`trim_gtfs.py` keeps stops inside the box `18.35,54.25,18.75,54.55` and
keeps the longest contiguous run of in-box stop times per trip. Adjust the
constants in the script for a different service area. The script copies
`transfers.txt` unchanged, so a strict GTFS validator may report references
to stops that were removed.

The server listens on `0.0.0.0:8080` by default. On the reference machine
(Apple Silicon), import took 3.52 s with 842 MB peak RSS; the server used
107 MB idle and about 175 MB after warm-up. Data directory size was 151 MB.

## Refresh

GTFS-RT and GBFS are fetched by the running server; they do not require a
re-import. A GTFS refresh does:

```sh
cd services/motis
# stop the server first
# download the feeds again, run the same trim commands
motis import -d data/motis-data
motis server -d data/motis-data
```

Keep the previous data directory until the new import succeeds if the
service must stay available.

## Health and status data

`GET /api/v1/health` returns `{"rt": true, "gbfs": true}` once at least one
update cycle has completed for every configured feed. It returns HTTP 400
while the first cycle is still running. A connection error or timeout means
the service is down.

Useful status signals:

- GTFS fetch time and `feed_info.txt` start/end dates for each feed;
- MOTIS `/api/v1/health` and a fixed `/api/v6/plan` probe;
- GTFS-RT age from the protobuf `FeedHeader.timestamp` or the upstream
  `Last-Modified` header;
- MEVO GBFS `last_updated` from `station_status.json`;
- predictor endpoint status at
  `https://delays.anotherk1t.be/predictions` (separate from MOTIS; see the
  handover notes).

## API

See `api-examples.md` for transit, bike, walk, and bike + transit requests.
All examples use a local-time timestamp with an explicit offset and
`maxMatchingDistance=250` for bike and walk. Timestamps in responses are
UTC (`Z`).

## Benchmark

See `benchmark/README.md`. The recorded run covers 15 Tri-City origin and
destination pairs and compares MOTIS, GraphHopper, and BRouter.
