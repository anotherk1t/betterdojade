# MOTIS `/api/v6/plan` examples

Base URL: `http://localhost:8080` (the server listens on port 8080 by
default). All examples use a local timestamp with an explicit UTC offset.
Responses use UTC (`Z`) timestamps.

`time` must be ISO 8601 with an offset. Warsaw uses `+01:00` in winter and
`+02:00` in summer. When building a URL by hand, encode the plus sign as
`%2B01:00`; `curl --data-urlencode` handles this automatically.

Coordinates are `latitude,longitude`.

The same transit request as a raw URL:

```text
http://localhost:8080/api/v6/plan?fromPlace=54.355,18.644&toPlace=54.518,18.531&time=2026-11-11T14:10:00%2B01:00&numItineraries=3
```

## Transit

Gdańsk Główny → Gdynia Główna:

```sh
curl -sG 'http://localhost:8080/api/v6/plan' \
  --data-urlencode 'fromPlace=54.355,18.644' \
  --data-urlencode 'toPlace=54.518,18.531' \
  --data-urlencode 'time=2026-11-11T14:10:00+01:00' \
  --data-urlencode 'numItineraries=3'
```

Expected: HTTP 200, three entries in `itineraries`, fastest about 2,340 s
with one transfer. A direct SKM option is about 2,820 s with no transfers.
Transit results are on `itineraries`, not `direct`.

Local transit example (Gdańsk Główny → Plac Solidarności):

```sh
curl -sG 'http://localhost:8080/api/v6/plan' \
  --data-urlencode 'fromPlace=54.355,18.644' \
  --data-urlencode 'toPlace=54.3605,18.6495' \
  --data-urlencode 'time=2026-11-11T14:10:00+01:00' \
  --data-urlencode 'directModes=WALK' \
  --data-urlencode 'transitModes=TRANSIT'
```

Expected: seven itineraries; the fastest is about 540 s with a tram leg.

## Bike

Gdańsk Główny → Sopot:

```sh
curl -sG 'http://localhost:8080/api/v6/plan' \
  --data-urlencode 'fromPlace=54.355,18.644' \
  --data-urlencode 'toPlace=54.4415,18.5605' \
  --data-urlencode 'time=2026-11-11T14:10:00+01:00' \
  --data-urlencode 'directModes=BIKE' \
  --data-urlencode 'transitModes=' \
  --data-urlencode 'maxMatchingDistance=250' \
  --data-urlencode 'maxDirectTime=7200'
```

Expected: HTTP 200, one entry in `direct`, about 2,954 s and 12,447 m.

- `transitModes=` (empty) disables transit for a direct-only query. Without
  it, MOTIS defaults to `TRANSIT`.
- `maxMatchingDistance=250` is required in practice for bike and walk near
  pedestrian zones. The server config default is 25, which can return no
  direct result when the coordinate snaps poorly.
- `maxDirectTime` defaults to 1,800 s; raise it for longer direct trips.

## Walk

Short walk, Gdańsk Główny → Plac Solidarności:

```sh
curl -sG 'http://localhost:8080/api/v6/plan' \
  --data-urlencode 'fromPlace=54.355,18.644' \
  --data-urlencode 'toPlace=54.3605,18.6495' \
  --data-urlencode 'time=2026-11-11T14:10:00+01:00' \
  --data-urlencode 'directModes=WALK' \
  --data-urlencode 'transitModes=' \
  --data-urlencode 'maxMatchingDistance=250'
```

Expected: one `direct` itinerary, about 745 s and 893 m.

Medium walk, Gdańsk Główny → Sopot:

```sh
curl -sG 'http://localhost:8080/api/v6/plan' \
  --data-urlencode 'fromPlace=54.355,18.644' \
  --data-urlencode 'toPlace=54.4415,18.5605' \
  --data-urlencode 'time=2026-11-11T14:10:00+01:00' \
  --data-urlencode 'directModes=WALK' \
  --data-urlencode 'transitModes=' \
  --data-urlencode 'maxMatchingDistance=250' \
  --data-urlencode 'maxDirectTime=14400'
```

Expected: one `direct` itinerary, about 9,946 s and 11,983 m.

## Bike + transit

Bike to the station, transit, bike from the station:

```sh
curl -sG 'http://localhost:8080/api/v6/plan' \
  --data-urlencode 'fromPlace=54.355,18.644' \
  --data-urlencode 'toPlace=54.518,18.531' \
  --data-urlencode 'time=2026-11-11T14:10:00+01:00' \
  --data-urlencode 'directModes=BIKE' \
  --data-urlencode 'transitModes=TRANSIT' \
  --data-urlencode 'preTransitModes=BIKE' \
  --data-urlencode 'postTransitModes=BIKE' \
  --data-urlencode 'maxMatchingDistance=250'
```

Expected: three itineraries, about 1,740–2,280 s, with BIKE access and
egress legs. The feeds set `bikes_allowed=false`, so the bike is not
carried on the vehicle.

## MEVO bike sharing

Direct rental:

```sh
curl -sG 'http://localhost:8080/api/v6/plan' \
  --data-urlencode 'fromPlace=54.355,18.644' \
  --data-urlencode 'toPlace=54.4415,18.5605' \
  --data-urlencode 'time=2026-11-11T14:10:00+01:00' \
  --data-urlencode 'directModes=RENTAL' \
  --data-urlencode 'transitModes=' \
  --data-urlencode 'directRentalFormFactors=BICYCLE' \
  --data-urlencode 'maxMatchingDistance=250' \
  --data-urlencode 'maxDirectTime=7200'
```

Expected: four direct `RENTAL` options, about 3,185–3,408 s and 12.2 km.
Rental legs include `rental.providerId` set to `mevo`, `rental.systemName`
set to `MEVO`, `rental.formFactor` set to `BICYCLE`, and `propulsionType` of
`ELECTRIC_ASSIST` or `HUMAN`.

MEVO plus transit:

```sh
curl -sG 'http://localhost:8080/api/v6/plan' \
  --data-urlencode 'fromPlace=54.355,18.644' \
  --data-urlencode 'toPlace=54.518,18.531' \
  --data-urlencode 'time=2026-11-11T14:10:00+01:00' \
  --data-urlencode 'directModes=RENTAL' \
  --data-urlencode 'transitModes=TRANSIT' \
  --data-urlencode 'preTransitModes=RENTAL' \
  --data-urlencode 'postTransitModes=RENTAL' \
  --data-urlencode 'directRentalFormFactors=BICYCLE' \
  --data-urlencode 'preTransitRentalFormFactors=BICYCLE' \
  --data-urlencode 'postTransitRentalFormFactors=BICYCLE' \
  --data-urlencode 'maxMatchingDistance=250'
```

Expected: three itineraries, about 2,040–2,700 s, with a MEVO egress leg
from Gdynia Główna.

## Response shape

Transit results:

```json
{
  "itineraries": [
    {
      "duration": 2820,
      "startTime": "2026-11-11T13:20:00Z",
      "endTime": "2026-11-11T14:07:00Z",
      "transfers": 0,
      "legs": [
        {
          "mode": "WALK",
          "duration": 180,
          "distance": 206.0,
          "realTime": false,
          "legGeometry": { "points": "...", "precision": 6 }
        },
        {
          "mode": "REGIONAL_RAIL",
          "routeShortName": "SKM",
          "headsign": "WEJHEROWO",
          "agencyName": "PKP Szybka Kolej Miejska w Trójmieście Sp. z o.o.",
          "startTime": "2026-11-11T13:23:00Z",
          "endTime": "2026-11-11T13:57:00Z",
          "scheduledStartTime": "2026-11-11T13:23:00Z",
          "scheduledEndTime": "2026-11-11T13:57:00Z",
          "realTime": false
        }
      ]
    }
  ]
}
```

Direct results are on `direct` and have the same itinerary/leg shape. A
direct query returns `itineraries: []`.

Leg geometry is an encoded polyline with `precision: 6`. Decode it with the
usual polyline algorithm, using 1e6 as the coordinate factor.

GTFS-RT, when the feed provides data for a leg, sets `realTime: true` and
adjusts `startTime` / `endTime` while keeping `scheduledStartTime` /
`scheduledEndTime`. The place objects also carry `arrivalTimestampReason` and
`departureTimestampReason` (`PREDICTED`, `PROPAGATED`, or `NO_RT_DATA`).
MOTIS does not return a separate numeric delay field.

## Other endpoints

```sh
# Feed update health. 200 with rt/gbfs true after the first update cycle;
# 400 while the first cycle is still running.
curl -s 'http://localhost:8080/api/v1/health'

# Rental stations and vehicles near a point.
curl -s 'http://localhost:8080/api/v1/rentals?point=54.355,18.644&radius=2000&providers=mevo'
```
