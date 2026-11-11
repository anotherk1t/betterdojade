# Roman — MOTIS routing migration handover

**Branch:** `roman/motis-routing`
**Goal:** replace the GraphHopper PT client with MOTIS, while keeping GraphHopper as a fallback until parity is verified.

## Status

This branch is a **starter, not an implementation**. It adds the tested
MOTIS configuration, data-preparation scripts, API examples, benchmark, and
spike notes. `src/routing/motis.js` is still a skeleton: it is not wired into
the app, has no URL construction or itinerary mapping, and throws when
called. The acceptance criteria below define the next milestone.

## Context

- Spike reports: `docs/spikes/motis-full-test.md`, `docs/spikes/bike-route-quality.md`, `docs/spikes/motis-memory-spike.md`
- Runnable artifacts: `services/motis/` (configuration, feed scripts, API examples, benchmark)
- MOTIS full test: import 3.52 s / 842 MB peak; server 107 MB idle, about 175 MB warm; transit/bike/walk/multimodal queries all returned HTTP 200.
- Gdańsk GTFS-RT: 250/250 trip-update entities matched at test time; other operators return `realTime: false`.
- Bike quality: competitive distance on 14/15 routes; one hard failure (Gdańsk → Brzeźno sand/unpaved loop). Use guardrails and label bike routing beta.
- Current app routing: `src/routing/graphhopper.js`, `src/routing/multimodal.js`.

## Data sources

URLs are the ones used in the 2026-11-11 spike. Re-check them before a
production refresh.

| Input | URL | Notes |
|---|---|---|
| MOTIS | `https://github.com/motis-project/motis/releases/download/v2.11.4/motis-macos-arm64.tar.bz2` | v2.11.4; use the matching release asset for other platforms |
| OSM | `https://download.geofabrik.de/europe/poland/pomorskie-latest.osm.pbf` | Pomorskie extract, clipped to `18.35,54.25,18.75,54.55` |
| Gdańsk GTFS | `https://ckan.multimediagdansk.pl/dataset/c24aa637-3619-4dc2-a171-a23eec8f2172/resource/30e783e4-2bec-4a7d-bb22-ee3e3b26ca96/download/gtfsgoogle.zip` | CKAN resource; rolling 15-day feed |
| Gdynia GTFS | `https://api.zdiz.gdynia.pl/pt/gtfs.zip` | ZDiZ Gdynia |
| SKM GTFS | `https://www.skm.pkp.pl/gtfs-mi-kpd.zip` | PKP SKM Tricity |
| Polregio GTFS | `https://mkuran.pl/gtfs/polish_trains.zip` | Unified Polish trains feed; agency `PR` extracted |
| Gdańsk GTFS-RT | `https://ckan2.multimediagdansk.pl/gtfs-rt?feed=tripUpdates` | GTFS-RT trip updates; protobuf; HTTP 301 to HTTPS |
| MEVO GBFS | `https://gbfs.urbansharing.com/rowermevo.pl/gbfs.json` | Official feed; requires `Client-Identifier` |
| Predictor | `https://delays.anotherk1t.be/predictions` | Existing delay-prediction service, independent of MOTIS |

Feed validity at test time:

| Feed | Validity | Size |
|---|---|---:|
| Gdańsk | 2026-11-11 .. 2026-11-25 | 27.1 MB |
| Gdynia | 2026-11-11 .. 2027-01-20 | 18.4 MB |
| SKM | 2026-10-19 .. 2026-12-12 | 15.3 MB |
| Polregio | 2026-11-10 .. 2026-12-11 | 6.1 MB |

### Gdańsk feed is a 15-day feed

The current Gdańsk GTFS is a rolling feed valid for 15 days
(`feed_info.end_date=20261125` at test time). With `num_days: 30`, Gdańsk bus
and tram service disappears after the feed end date; local queries then
return only walking. Refresh the feed at least every 14 days, or cap the
timetable horizon to the feed and expose the coverage gap in the status page.
Do not enable `extend_calendar` just to fill the gap: it fabricates service.

### MEVO GBFS replaces the dead middleware

The old `mevo-middleware.fly.dev` host no longer resolves. Use the official
endpoint `https://gbfs.urbansharing.com/rowermevo.pl/gbfs.json` with a
`Client-Identifier` header. MOTIS supports per-feed headers, so this works
directly in `services/motis/config.example.yml`. Use a stable, descriptive
identifier for the deployment.

### GTFS-RT scope

GTFS-RT is configured only for the Gdańsk dataset. Gdynia, SKM, and Polregio
have no feed configured. MOTIS marks adjusted legs with `realTime: true`,
keeps `scheduledStartTime` / `scheduledEndTime`, and sets
`arrivalTimestampReason` / `departureTimestampReason`. Without a feed,
`realTime` is `false` and the reason is `NO_RT_DATA`.

## Status page data requirements

The status page should show data freshness separately from service health.
Every value needs a timestamp or age; never show cached data as current.
Use the label **GTFS-RT** in the UI for feed-based adjustments.

| Signal | Source | Healthy | Warning / error |
|---|---|---|---|
| GTFS last update | Per feed: stored fetch time, HTTP `Last-Modified`, and `feed_info.txt` `feed_start_date` / `feed_end_date` | Fetch < 24 h old; feed end date at least 7 days ahead | Warn if fetch > 48 h or < 5 days remain; error if the feed is expired |
| MOTIS health | `GET http://localhost:8080/api/v1/health` | HTTP 200 with `{"rt": true, "gbfs": true}` | HTTP 400 means the first feed update cycle is incomplete; connection error or timeout means MOTIS is down |
| GTFS-RT age | Protobuf `FeedHeader.timestamp` from the Gdańsk trip-updates feed; fall back to HTTP `Last-Modified` / `Date` | Age < 2 min (server polls every 60 s) | Warn > 5 min; error > 15 min or fetch failure |
| MEVO GBFS | `gbfs.json` with `Client-Identifier`, then `station_status.json` `last_updated` | HTTP 200 and age < 2 min | Warn > 5 min; error > 15 min, invalid JSON, or HTTP failure |
| Predictor health | `GET https://delays.anotherk1t.be/predictions` | HTTP 200 and a non-empty `predictions` array | Warn if the array is empty; error on non-200, timeout, or parse failure |
| Routing probe (optional) | Fixed `GET /api/v6/plan` query | HTTP 200 and at least one itinerary or direct route | Error on non-200, empty result, or timeout |

Additional requirements:

- Show per-feed GTFS status (Gdańsk, Gdynia, SKM, Polregio), not one combined
  value, because the feeds expire on different dates.
- Show the GTFS-RT feed age next to the transit data, and distinguish “feed
  age” from “MOTIS applied it”.
- Poll health and freshness at most once per minute; keep the last known
  value and its timestamp during transient failures.
- Link a stale or failed tile to the relevant upstream URL so the operator
  can check the source directly.

## Tasks

1. Implement `src/routing/motis.js`:
   - `/api/v6/plan` query with timezone offset;
   - `maxMatchingDistance=250` for bike/walk;
   - map itineraries/legs into the existing route model.
2. Add a MOTIS base URL env var and a GraphHopper fallback switch.
3. Add a GTFS refresh + MOTIS re-import script using the artifacts in
   `services/motis/`:
   - current Gdańsk GTFS (15-day feed), Gdynia, SKM, Polregio;
   - official MEVO GBFS: `https://gbfs.urbansharing.com/rowermevo.pl/gbfs.json` + `Client-Identifier`.
4. Add guardrails:
   - filter >10% unpaved or obvious sand/loops;
   - handle pedestrian-only destinations;
   - label bike routing beta.
5. Add tests for mode mapping, time parsing, fallback, and GTFS-RT flags.
6. Update `src/routing/multimodal.js` to use MOTIS for PT and keep bike/walk behavior.

## Acceptance criteria

- Fixed A→B returns transit, bike, walk, and multimodal routes.
- GTFS-RT flags appear for Gdańsk; no crashes when the feed is absent.
- No GraphHopper dependency for PT.
- `npm run test:run` and `npm run build` pass.
- Memory stays under ~1 GB for the MOTIS service.
- The starter artifacts in `services/motis/` remain runnable and documented.

## First commits

1. `feat(routing): add MOTIS client skeleton`
2. `feat(routing): map MOTIS itineraries to route model`
3. `feat(data): add GTFS refresh and re-import script`
4. `feat(mevo): use official GBFS feed`
5. `test(routing): cover MOTIS mapping and fallback`

## References

- `services/motis/README.md` — data sources, build/import/server commands, health.
- `services/motis/api-examples.md` — `/api/v6/plan` transit, bike, walk, bike + transit, MEVO.
- `services/motis/benchmark/README.md` — benchmark setup, metrics, recorded results.
