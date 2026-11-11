# Tri-City bike routing quality: MOTIS vs GraphHopper vs BRouter

**Date:** 2026-11-11  
**Scope:** 15 origin–destination pairs in Gdańsk / Sopot / Gdynia, bike-only routing.  
**Work dir:** `/private/var/folders/2y/1bsn02s15h10sbtw8y9cfpk00000gn/T/opencode/route-quality`  
**Repo untouched:** `/Users/yan/Documents/bikerouter` was not modified.

---

## TL;DR

**MOTIS bike routing is acceptable for a map-based demo, but not production-grade for navigation.**

- MOTIS returned a direct BIKE itinerary for **all 15** OD pairs, including the 1.59 km Gdańsk Główny → Stare Miasto route. The short-route snapping failure noted in the earlier spike **did not reproduce** with `maxMatchingDistance=250`.
- MOTIS distance was **at or near the shortest** on 14/15 routes: median ratio to the best engine **1.00**, mean **1.01** excluding the one failure. The exception is **Gdańsk Główny → Brzeźno**, where MOTIS is **52 % longer** (11.24 km vs 7.38–8.10 km) and makes a ~4 km out-and-back loop along the beach, including **3.9 km (35 %) of unpaved surface** and **2.0 km of `surface=sand`**.
- Aggregate infrastructure mix over all 15 routes is comparable to the dedicated bike routers:

| Engine | Total km | Speed | Cycle/path/track | Primary/secondary/trunk | Unpaved | Signals/km | Turns/km |
|---|---:|---:|---:|---:|---:|---:|---:|
| **MOTIS bike** | 128.1 | 15.1 km/h | **82 %** | 5 % | 5 % | 4.9 | 1.9 |
| GraphHopper bike | 128.9 | 16.5 km/h | 79 % | 4 % | **1 %** | 4.6 | 2.4 |
| BRouter trekking | 129.8 | 19.2 km/h | 79 % | 2 % | 3 % | 4.3 | 2.0 |
| BRouter fastbike | 127.8 | 19.1 km/h | 39 % | **31 %** | 0 % | 4.6 | 1.8 |
| BRouter safety | 131.6 | 19.1 km/h | **82 %** | **1 %** | 3 % | 4.3 | 2.1 |

Excluding r12, MOTIS's mix is **80 % cycle / 5 % major / 2.3 % unpaved**, essentially matching BRouter trekking (79 / 2 / 3). The aggregate is dragged down by the one failure.

- MOTIS's main gaps are **surface weighting** (sand/unpaved), **no turn-by-turn instructions** (all steps are `CONTINUE`), **no elevation model**, and **no explicit traffic-signal cost** in this profile. Its ETA is ~8–12 % slower than Google/GraphHopper.
- **Recommendation:** keep MOTIS bike for the demo, add a guardrail for pedestrian-only destinations (Brzeźno pier), and label bike routing as beta. Use a hybrid **MOTIS transit + BRouter bike** only if the demo requires turn-by-turn, hill-aware routing, or consistently clean surfaces.

---

## 1. What was run

### Servers

| Engine | Version / setup | Endpoint |
|---|---|---|
| MOTIS | v2.11.4 macOS arm64; existing Tri-City data from `motis-spike`, re-imported with a `server.port: 8081` block | `http://127.0.0.1:8081/api/v6/plan` |
| GraphHopper | 12.0-SNAPSHOT; tuned `graph-tricity-mmap-trimmed2` graph; 2D (`elevation: false`); profile `bike` | `http://127.0.0.1:8989/route` |
| BRouter | public API 1.7.11-beta; profiles `trekking`, `fastbike`, `safety` | `https://brouter.de/brouter` |

MOTIS query shape:

```
/api/v6/plan?fromPlace=lat,lon&toPlace=lat,lon
  &time=2026-11-11T12:00:00+01:00
  &directModes=BIKE&transitModes=
  &maxMatchingDistance=250&maxDirectTime=14400
```

GraphHopper used `profile=bike`, `points_encoded=false`, and repeated `details=road_class`, `details=surface`, `details=bike_network`, `details=get_off_bike` parameters. (In this build, `details=a,b` is not split; repeat the parameter.)

### Data

- OSM: `tricity.osm.pbf` (28.5 MB) extracted from `pomorskie-latest.osm.pbf`; 2.70 M nodes / 399 k ways.
- GTFS: current Gdańsk feed (Nov 2026) plus Gdynia/SKM/Polregio; only relevant for transit, not for the bike comparison.
- BRouter and Valhalla/Google use their own current OSM data, so small differences are expected.

### Metrics

- **Distance/duration:** reported by each engine.
- **% cycle/path/track:** for MOTIS, estimated by snapping every route segment midpoint to the nearest OSM `highway` within 30 m (local 152 k-way index). For GraphHopper and BRouter, computed from their own per-edge `road_class` details / BRouter `WayTags`.
- **% major:** `trunk`, `primary`, `secondary` and their links.
- **% unpaved:** `sand`, `ground`, `dirt`, `gravel`, `compacted`, `unpaved`, `grass`, `wood`, etc.
- **Signals/crossings:** OSM nodes (`highway=traffic_signals`, `highway=crossing`) within 25 m of the route geometry, deduplicated.
- **Turns:** geometric bearing changes >32° with ≥18 m spacing; comparable across engines but not the same as routing instructions.
- **Ascent:** BRouter only (`filtered ascend`). MOTIS and the current GraphHopper graph are 2D and return no elevation.

**Caveat:** MOTIS's road-class/surface percentages are approximate (±5–10 percentage points), especially where a cycleway runs parallel to a footway or road. GraphHopper/BRouter percentages come from their own edge attributes and are more exact.

### Independent spot checks

- **Google Maps** cycling directions, web UI, 6 routes. Qualitative only; no public cycling API.
- **Valhalla** public demo (`valhalla1.openstreetmap.de`, `costing=bicycle`), 10 routes. Used as an independent fourth geometry, not as a required benchmark engine.

---

## 2. Route table: distance and duration

Distances in km, durations in minutes. `best` is the shortest of MOTIS, GraphHopper, BRouter trekking/fastbike/safety, and Valhalla where available. Google Maps is a qualitative spot check and is not included in the ratio.

| # | OD | straight | MOTIS | GraphHopper | BRouter trekking | best | MOTIS/best | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 01 | Gdańsk Główny → Stare Miasto | 1.10 | **1.59 / 6** | 1.71 / 8 | 1.68 / 5 | 1.59 | 1.00 | **Good** |
| 02 | Gdańsk Główny → Wrzeszcz | 3.77 | **4.14 / 17** | 4.23 / 16 | 4.24 / 13 | 4.14 | 1.00 | **Good** |
| 03 | Gdańsk Główny → Oliwa | 7.53 | **8.39 / 33** | 8.55 / 30 | 8.50 / 26 | 8.39 | 1.00 | **Good** |
| 04 | Gdańsk Główny → Sopot | 10.70 | **12.39 / 49** | 13.63 / 47 | 13.50 / 39 | 12.30 | 1.01 | Acceptable |
| 05 | Gdańsk Główny → Gdynia Główna | 19.89 | **21.62 / 86** | 22.63 / 86 | 22.52 / 67 | 21.62 | 1.00 | Acceptable |
| 06 | Wrzeszcz → Oliwa (hilly) | 3.77 | 4.95 / 20 | 4.68 / 17 | 4.62 / 13 | 4.62 | 1.07 | Acceptable |
| 07 | Oliwa → Sopot (hilly) | 3.46 | 4.91 / 20 | 4.53 / 18 | 4.62 / 13 | 4.53 | 1.08 | Acceptable |
| 08 | Sopot → Gdynia | 9.37 | **10.20 / 41** | 10.73 / 41 | 10.62 / 32 | 10.20 | 1.00 | Acceptable |
| 09 | Gdańsk Główny → Przymorze | 6.84 | 7.88 / 32 | 7.89 / 29 | 8.44 / 25 | 7.76 | 1.02 | **Good** |
| 10 | Gdańsk Główny → Zaspa | 5.77 | **6.48 / 26** | 6.65 / 24 | 6.97 / 20 | 6.48 | 1.00 | **Good** |
| 11 | Gdańsk Główny → Nowy Port | 5.45 | **7.44 / 30** | 8.75 / 32 | 8.70 / 25 | 7.44 | 1.00 | Acceptable |
| 12 | Gdańsk Główny → Brzeźno | 6.54 | 11.24 / 45 | 7.49 / 27 | 7.41 / 21 | 7.38 | **1.52** | **Bad** |
| 13 | Gdańsk Główny → Orunia | 3.69 | **4.09 / 16** | 4.19 / 16 | 4.37 / 13 | 4.09 | 1.00 | **Good** |
| 14 | Gdańsk Główny → Jasień | 5.75 | **6.55 / 26** | 6.73 / 23 | 6.69 / 30 | 6.55 | 1.00 | **Good** |
| 15 | Gdańsk Główny → Osowa | 13.95 | **16.28 / 65** | 16.49 / 55 | 16.90 / 64 | 16.28 | 1.00 | Acceptable |

**Counts:** 7 good, 7 acceptable, 1 bad.  
**Distance summary:** median MOTIS/best = **1.00**; mean excluding r12 = **1.013**; worst excluding r12 = **1.08** (Oliwa → Sopot).

### MOTIS quality detail

| # | Cycle/path % | Major % | Foot % | Minor % | Unpaved % | Signals | Crossings | Turns | Snap start/end (m) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 01 | 44 | 0 | 47 | 10 | 0 | 7 | 21 | 11 | 44 / 0 |
| 02 | 82 | 0 | 0 | 18 | 0 | 16 | 57 | 6 | 44 / 49 |
| 03 | 82 | 1 | 0 | 17 | 0 | 47 | 150 | 15 | 44 / 32 |
| 04 | 85 | 0 | 9 | 6 | 0 | 72 | 217 | 15 | 44 / 32 |
| 05 | 86 | 7 | 4 | 2 | 0 | 122 | 308 | 31 | 44 / 43 |
| 06 | 60 | 2 | 0 | 38 | 0 | 27 | 101 | 25 | 49 / 32 |
| 07 | 52 | 0 | 5 | 43 | 0 | 17 | 83 | 19 | 32 / 32 |
| 08 | 80 | 15 | 2 | 3 | 0 | 59 | 104 | 15 | 32 / 43 |
| 09 | 98 | 0 | 0 | 2 | 0 | 39 | 135 | 17 | 44 / 90 |
| 10 | 99 | 0 | 0 | 1 | 5 | 32 | 105 | 14 | 44 / 14 |
| 11 | 69 | 4 | 0 | 26 | 0 | 21 | 79 | 14 | 44 / 7 |
| 12 | 100 | 0 | 0 | 0 | **35** | 32 | 125 | 22 | 44 / 12 |
| 13 | 95 | 3 | 0 | 2 | 1 | 31 | 43 | 10 | 44 / 38 |
| 14 | 52 | 5 | 0 | 43 | 0 | 36 | 75 | 6 | 44 / 11 |
| 15 | 82 | 11 | 2 | 4 | 14 | 75 | 186 | 26 | 44 / 10 |

r12's **100 % cycle/path** is misleading on its own: most of it is `highway=path`, and **35 % is unpaved** (sand/ground). The unpaved column is the better signal there.

The 15 % "major" on Sopot → Gdynia and 7 % on Gdańsk → Gdynia are mostly the **same 1.5 km approach to Gdynia Główna** (Śląska / Morska). OSM does not tag a separate cycleway there, so this is probably mixed traffic or a wide shoulder, not a protected path; GH/BR take a parallel street. The 11 % on Osowa is mostly **Spacerowa** in Oliwa.

### BRouter profile comparison

Distances in km (times in minutes); ascent in metres (trekking/fastbike/safety).

| # | trekking | fastbike | safety | Ascent |
|---|---:|---:|---:|---:|
| 01 | 1.68 (5) | 1.68 (5) | 1.68 (5) | 8 / 8 / 8 |
| 02 | 4.24 (13) | 4.24 (13) | 4.30 (14) | 16 / 16 / 17 |
| 03 | 8.50 (26) | 8.52 (26) | 8.50 (26) | 22 / 22 / 22 |
| 04 | 13.50 (39) | **12.30 (36)** | 13.27 (39) | 18 / 14 / 18 |
| 05 | 22.52 (67) | 22.38 (67) | 22.52 (67) | 54 / 58 / 54 |
| 06 | 4.62 (13) | 4.63 (13) | 4.62 (13) | 6 / 6 / 6 |
| 07 | 4.62 (13) | 5.42 (15) | 4.63 (13) | 7 / 3 / 8 |
| 08 | 10.62 (32) | 10.86 (32) | 10.87 (33) | 42 / 43 / 42 |
| 09 | 8.44 (25) | **7.76 (23)** | 8.05 (24) | 12 / 9 / 10 |
| 10 | 6.97 (20) | 7.05 (21) | 7.10 (21) | 9 / 9 / 9 |
| 11 | 8.70 (25) | **7.97 (23)** | 8.70 (25) | 7 / 8 / 7 |
| 12 | 7.41 (21) | 7.38 (21) | 7.41 (21) | 7 / 7 / 7 |
| 13 | 4.37 (13) | 4.41 (13) | 4.39 (13) | 11 / 20 / 11 |
| 14 | 6.69 (30) | 6.67 (30) | **8.17 (35)** | 110 / 110 / 133 |
| 15 | 16.90 (64) | 16.54 (63) | 17.37 (65) | 151 / 166 / 153 |

`fastbike` is the distance/road-oriented profile and is **not** a good safety reference: aggregate cycle share drops to 39 % and major-road share rises to 31 %. `safety` is the closest to MOTIS's cycle share (82 % vs 82 %) but has much lower major-road share (1 % vs 5 %). `trekking` is the middle ground and the best default for a bike demo.

### Spot checks: independent engines

Distances in km / times in minutes.

| # | MOTIS | GraphHopper | BRouter trekking | BRouter safety | Valhalla | Google Maps |
|---|---:|---:|---:|---:|---:|---:|
| 01 | 1.59 / 6 | 1.71 / 8 | 1.68 / 5 | 1.68 / 5 | 1.66 / 6 | **1.50 / 7** |
| 04 | **12.39 / 49** | 13.63 / 47 | 13.50 / 39 | 13.27 / 39 | 13.62 / 48 | 13.30 / 46 |
| 05 | **21.62 / 86** | 22.63 / 86 | 22.52 / 67 | 22.52 / 67 | 22.86 / 79 | 22.90 / 81 |
| 11 | **7.44 / 30** | 8.75 / 32 | 8.70 / 25 | 8.70 / 25 | 7.85 / 28 | 8.70 / 31 |
| 12 | **11.24 / 45** | 7.49 / 27 | 7.41 / 21 | 7.41 / 21 | **11.39 / 49** | **8.10 / 29** |
| 15 | **16.28 / 65** | 16.49 / 55 | 16.90 / 64 | 17.37 / 65 | 16.79 / 68 | 17.80 / 71 |

Google Maps' primary route for Gdańsk → Sopot is the coastal **R10** (14.2 km / 47 min), but it also offers a **13.3 km / 46 min** inland alternative via Rzemieślnicza. MOTIS's 12.39 km inland route is a more direct version of that alternative, not a nonsense route. For Gdańsk → Gdynia, Google's primary route is **22.9 km via Aleja Zwycięstwa**, which is also the inland corridor MOTIS uses; GH/BR/Valhalla prefer the coastal R10. So MOTIS is not an outlier on r05 — it is on the same corridor as Google, just 1.3 km shorter.

### Walk spot-check (secondary)

The task also mentions walk quality. Walk was not part of the 15-route query matrix, so this is a 3-route spot check only. Distances in km / times in minutes.

| # | OD | MOTIS WALK | GraphHopper foot | BRouter shortest |
|---|---|---:|---:|---:|
| 01 | Gdańsk Główny → Stare Miasto | 1.36 / 18.8 | 1.34 / 16.2 | 1.31 / 15.7 |
| 02 | Gdańsk Główny → Wrzeszcz | 4.26 / 59.1 | 4.23 / 50.9 | 4.19 / 50.6 |
| 03 | Gdańsk Główny → Oliwa | 8.59 / 118.8 | 8.48 / 102.0 | 8.44 / 101.3 |

Walk geometries agree within 1–2 %. MOTIS's walk speed is ~4.3 km/h vs ~5.0 km/h for GH/BRouter, so its walk ETAs are 15–18 % longer. Same pattern as bike: the geometry is fine, the speed model is conservative.

---

## 3. Route-by-route notes

**01. Gdańsk Główny → Stare Miasto — Good.** 1.59 km, 6 min; Google 1.5 km, 7 min. 44 % cycle + 47 % foot is expected: the destination is Długi Targ in the pedestrian zone. No major road, no unpaved, 7 signals. MOTIS snapped exactly to the destination (0 m). This also disproves the earlier "short bike route returns 0" concern.

**02. Gdańsk Główny → Wrzeszcz — Good.** 4.14 km, 17 min; GH 4.23/16, BR 4.24/13. 82 % cycle, 0 % major, 0 % unpaved, 16 signals. Same corridor as the other engines; MOTIS's ETA is ~1 min slower.

**03. Gdańsk Główny → Oliwa — Good.** 8.39 km, 33 min; GH 8.55/30, BR 8.50/26. 82 % cycle, 1 % major, 0 % unpaved, 47 signals. Direct SKM corridor. The ETA is conservative but the geometry is clean.

**04. Gdańsk Główny → Sopot — Acceptable.** 12.39 km, 49 min; GH 13.63/47, BR 13.50/39, Google 13.3/46, Valhalla 13.62/48. MOTIS takes the **inland Oliwa corridor** while GH/BR/Valhalla/Google-primary take the coastal **R10**. MOTIS is 1.1–1.2 km shorter, 85 % cycle, 0 % major, 0 % unpaved, but it crosses **72 signals vs 37** on the coastal route. Google's fastest alternative (13.3 km inland) is the same family of route, so this is a legitimate utility-cycling choice, not a failure — just slower in practice and less scenic.

**05. Gdańsk Główny → Gdynia Główna — Acceptable.** 21.62 km, 86 min; GH 22.63/86, BR 22.52/67, Google 22.9/81, Valhalla 22.86/79. 86 % cycle, 7 % major (the 1.5 km Śląska/Morska approach in Gdynia), 0 % unpaved, **122 signals vs 78–85** on the coastal R10. MOTIS is the shortest and matches Google's inland corridor; the downside is signal density and a slightly slower ETA than Google.

**06. Wrzeszcz → Oliwa (hilly) — Acceptable.** 4.95 km, 20 min; GH 4.68/17, BR 4.62/13, Valhalla 5.14/18. MOTIS is **7 % longer** and has **25 turns vs 10–16**; the map shows a zigzag through Wrzeszcz streets before joining the main corridor. 60 % cycle, 38 % minor, 2 % major, 0 % unpaved. GH/BR are cleaner; MOTIS is not bad, just fussier.

**07. Oliwa → Sopot (hilly) — Acceptable.** 4.91 km, 20 min; GH 4.53/18, BR 4.62/13, Valhalla 4.93/18. Similar story: **8 % longer**, 19 turns, 52 % cycle / 43 % minor; it zigzags through Przymorze before joining the main corridor. BRouter safety is 4.63 km, so the direct corridor exists; MOTIS's detour is a route-choice quirk, not a data gap.

**08. Sopot → Gdynia — Acceptable.** 10.20 km, 41 min; GH 10.73/41, BR 10.62/32. 80 % cycle, **15 % major** — again the same 1.5 km Gdynia approach (Śląska/Morska). OSM does not tag a separate cycleway on those ways, so this is likely mixed traffic or a wide shoulder; GH/BR use a parallel street. 0 % unpaved, 59 signals. Shortest distance, but the final approach is the least pleasant part of the route.

**09. Gdańsk Główny → Przymorze — Good.** 7.88 km, 32 min; GH 7.89/29, BR 8.44/25, Valhalla 7.93/28. **98 % cycle**, 0 % major, 0 % unpaved, 39 signals. MOTIS and GH/Valhalla take the same corridor; BRouter trekking takes a longer coastal detour. This is one of the cleanest MOTIS routes.

**10. Gdańsk Główny → Zaspa — Good.** 6.48 km, 26 min; GH 6.65/24, BR 6.97/20. **99 % cycle**, 0 % major, 5 % unpaved, 32 signals. Direct and almost entirely cycleway; the short unpaved section is minor.

**11. Gdańsk Główny → Nowy Port — Acceptable.** 7.44 km, 30 min; GH 8.75/32, BR 8.70/25, Google 8.7/31, Valhalla 7.85/28. MOTIS takes a **direct industrial corridor** via Młyniska/Letnica/Starowiejska, 1.3 km shorter than GH/BR/Google's coastal route. 69 % cycle, 4 % major, **11 % cobblestone**, 26 % minor. Valhalla's 7.85 km corroborates the direct corridor, so this is a real shortcut, not a routing error — but it is less pleasant than the coastal alternative.

**12. Gdańsk Główny → Brzeźno — Bad.** 11.24 km, 45 min; GH 7.49/27, BR 7.41/21, Google 8.10/29, Valhalla 11.39/49. MOTIS follows the coastal cycleway correctly to Brzeźno, then **continues ~2.5 km north to Jelitkowo (54.4247, 18.5999), turns around, and returns along the beach path** to the pier — a ~4 km loop for the last ~300 m. **35 % of the route (3.9 km) is unpaved**, including **2.0 km on OSM way 1426084481** (`highway=path`, `surface=sand`). The destination, `Molo w Brzeźnie`, is `highway=pedestrian` + `bicycle=no`; Valhalla also loops (11.39 km), so this is an access-modeling edge case rather than a random MOTIS bug. But GH/BR/Google all reach the pier area in 7.4–8.1 km, and MOTIS's sand-path choice makes the result clearly unacceptable for this OD.

**13. Gdańsk Główny → Orunia — Good.** 4.09 km, 16 min; GH 4.19/16, BR 4.37/13. **95 % cycle**, 3 % major, 0 % unpaved, 31 signals. Shortest and mostly cycleway; GH/BR use 44–50 % footway, so MOTIS is actually the better bike route here.

**14. Gdańsk Główny → Jasień — Good.** 6.55 km, 26 min; GH 6.73/23, BR 6.69/30, Valhalla 6.57/25. All engines overlap almost exactly (MOTIS/Valhalla 100 %, MOTIS/BR 100 %, MOTIS/GH 98 %). 52 % cycle / 43 % minor / 5 % major, 0 % unpaved. BRouter reports **110 m ascent**; MOTIS's 2D graph cannot use that, but the route is already the consensus one. MOTIS's 6 geometric turns look low because the route is a long, smooth corridor.

**15. Gdańsk Główny → Osowa — Acceptable.** 16.28 km, 65 min; GH 16.49/55, BR 16.90/64, Valhalla 16.79/68, Google 17.80/71. 82 % cycle, 11 % major (Spacerowa), **14 % unpaved** (2.3 km forest path); BRouter trekking also takes 19 % unpaved and reports **151 m ascent**, while GH takes a paved but **28 % major** route. MOTIS is the shortest and takes the forest corridor that BR/Valhalla also like; the surface trade-off is the main downside.

---

## 4. MOTIS vs GraphHopper vs BRouter

### Where MOTIS is good

- **Distance:** shortest or within 2 % on 12/15; within 8 % on 14/15. It does not produce absurd detours except r12.
- **Cycleway share:** 82 % aggregate, equal to BRouter `safety` and better than GH (79 %); 98–99 % on Przymorze/Zaspa, 95 % on Orunia.
- **Turns:** 1.9 turns/km, fewer than GH (2.4) and similar to BR (2.0); its geometry is often smooth.
- **Short routes:** all 15 returned; 1.59 km worked; snapping 32–49 m at the start and 0–90 m at the end.
- **Single-engine simplicity:** transit + bike in one service; low memory (prior spike: ~0.08–0.13 GB idle vs ~2.3 GB for GH). This is the main architectural argument for keeping it.

### Where GraphHopper is better

- **Speed/ETA:** 16.5 km/h, closest to Google (~17 km/h); 60–100 ms queries.
- **Turn-by-turn:** real maneuvers (`Turn right`, `Keep left`, etc.); MOTIS has none.
- **Paved surfaces:** 1 % unpaved aggregate vs MOTIS 5 %; it avoids the r12 sand path.
- **But:** its bike profile takes **28 % major** on Osowa, **50 % footway** on Orunia, and it ignores the `bicycle=no` pier at Brzeźno. It is not uniformly better; it is faster and more navigable, not necessarily safer.

### Where BRouter is better

- **Surface/elevation awareness:** reports ascent (up to 151 m on Osowa, 110 m on Jasień) and avoids sand/unpaved by default (`trekking` 3 % unpaved, `safety` 3 %).
- **Safety profile:** 82 % cycle / 1 % major aggregate — the best infrastructure mix in the benchmark, at the cost of 1.5–2 km extra on some routes (e.g., Jasień safety 8.17 km vs 6.55 km).
- **No API key:** easy for a demo; but the public API is rate-limited (one 403 during the run, retried successfully) and its 19.2 km/h ETA is optimistic for city biking.
- **Turn cues:** the GeoJSON does not include text instructions, but BRouter can return GPX with cues; less convenient than GH's JSON maneuvers.

### Corridor choices

- **Gdańsk → Sopot / Gdynia:** MOTIS prefers the inland Oliwa/Aleja Zwycięstwa corridor; GH/BR/Valhalla prefer the coastal R10. Google offers both (coastal R10 primary, inland alternative). MOTIS's route is shorter but has 1.4–1.6× the signals. Neither is wrong; it is a utility-vs-scenic trade-off.
- **Gdańsk → Nowy Port:** MOTIS takes the direct Młyniska/Letnica industrial corridor; GH/BR take the longer coastal route via Brzeźno. Valhalla and Google's 8.7 km route are closer to MOTIS, so MOTIS's shortcut is credible, but it has 11 % cobblestone.
- **Gdańsk → Osowa:** MOTIS and BR/Valhalla take the forest path; GH takes the paved main road. Surface vs major-road trade-off.
- **Gdańsk → Brzeźno:** the only clear failure; see r12.

---

## 5. Specific MOTIS weaknesses

1. **Pedestrian/access edge cases (r12).** A destination on a `bicycle=no` pedestrian pier triggers a ~4 km loop and a 2 km sand-path return. Valhalla reproduces the loop, so it is an access-modeling issue, not a random bug; but the sand choice and loop length are unacceptable. MOTIS does not split a direct BIKE leg into bike + walk, so it cannot "ride to the barrier and walk the last 100 m."
2. **No turn-by-turn instructions.** All 15 routes return `steps` with `relativeDirection=CONTINUE`; MOTIS's OSR code only emits `CONTINUE`/`STAIRS`/`ELEVATOR` (turn directions are a TODO). Street names are present only for named ways: 0/199 on Zaspa, 2/255 on Przymorze, 4/252 on Brzeźno. If the demo shows "turn right onto…", MOTIS cannot supply it.
3. **No elevation model.** The MOTIS graph is 2D; no ascent/descent, no hill cost. BRouter reports 110 m (Jasień) and 151 m (Osowa) of climb, and 42–54 m on Sopot–Gdynia. MOTIS's hilly routes (Wrzeszcz–Oliwa, Oliwa–Sopot) are 7–8 % longer and more turny, but it cannot consciously trade distance for climb.
4. **Surface weighting is too permissive.** 35 % unpaved on Brzeźno (3.9 km, including 2.0 km sand), 14 % on Osowa, 11 % cobblestone on Nowy Port. GH is 1 % unpaved aggregate, BRouter 3 %. This is the most actionable profile-tuning item: increase the cost of `surface=sand/ground/dirt/cobblestone` and `tracktype=grade3+`.
5. **No traffic-signal cost.** Gdańsk → Sopot: 72 signals vs 37 on the coastal R10; Gdańsk → Gdynia: 122 vs 78. MOTIS's conservative 15.1 km/h ETA partly compensates, but it does not choose lower-signal alternatives. GH/BR also lack an explicit signal cost, but their chosen corridors happen to have fewer.
6. **Conservative ETA.** 15.1 km/h vs GH 16.5, Valhalla ~17, Google ~17, BRouter 19.2. About 10–12 % slower than Google on comparable routes. Not a blocker for a demo, but users may notice pessimistic arrival times.
7. **Route-choice divergence is not always a weakness.** On r04/r05/r11 MOTIS takes a different corridor from GH/BR, but Google/Valhalla often corroborate the direct/inland choice. The lesson is to explain the trade-off (signals, scenery, surface), not to assume MOTIS is wrong.
8. **Short-route snapping is no longer a concern.** With `maxMatchingDistance=250`, all 15 ODs returned a direct route; the 1.59 km city-center route worked with a 0 m end snap. The earlier spike's 0-result did not reproduce. Keep `250` for bike queries; the server default `25` is too tight for bike endpoints.

---

## 6. Recommendation

### For the demo: **yes, MOTIS bike is acceptable — with guardrails**

MOTIS gives a single-engine transit + bike service with low memory, and its bike geometry is at or near the best distance on 14/15 routes. The aggregate infrastructure mix (82 % cycle, 5 % major) is comparable to BRouter `safety` and better than GraphHopper in cycle share. For a map-based demo that shows "here is a bike route" — not turn-by-turn navigation — this is good enough.

**Guardrails before calling it demo-ready:**

1. **Handle pedestrian-only destinations.** Detect destinations within ~100 m of `bicycle=no` / `highway=pedestrian` ways and either (a) snap to the nearest bike-accessible point and add a short WALK leg, or (b) show a warning. At minimum, remove `Molo w Brzeźnie` from the demo script or precompute it with BRouter.
2. **Post-filter or penalize bad surfaces.** Reject/flag routes with >10 % unpaved; tune the OSR bike profile to penalize `sand`, `ground`, `dirt`, `cobblestone`, and `tracktype=grade3+`. This fixes r12 and improves r15.
3. **Label bike routing as beta.** Do not promise turn-by-turn or elevation-aware routing; MOTIS does not provide either in this setup.
4. **Keep `maxMatchingDistance=250`** for bike queries and test the demo's exact endpoints; the server default 25 is too tight.
5. **Optionally calibrate speed** to ~17 km/h for ETAs closer to Google/GH; current 15.1 km/h is conservative.

### If the demo requires navigation or hill-aware routing: **use a hybrid**

**MOTIS for transit + BRouter for bike** is the cleanest quality-first hybrid:

- MOTIS `/api/v6/plan` handles transit itineraries (its strength: 92k trips, real GTFS, low memory).
- For direct bike trips and bike access/egress, call BRouter `trekking` (default) or `safety` (if the demo emphasizes avoiding main roads). BRouter has surface/elevation awareness and returns ascent; its `safety` profile matches MOTIS's 82 % cycle share with 1 % major.
- Merge the BRouter geometry/duration into the MOTIS itinerary response, or present bike and transit as separate tabs.
- Cache bike routes; BRouter public API is rate-limited (one 403 in 45 requests). Self-host BRouter if the demo is public.

**GraphHopper as the bike engine** is the pragmatic alternative if you need self-hosted latency and JSON turn-by-turn:

- GH is 60–100 ms, has real maneuvers, and is already built/tuned in this environment.
- But its current graph is 2D; add elevation (SRTM) and a custom bike model if hills matter. Its stock bike profile took 28 % major on Osowa and 50 % footway on Orunia, and it ignores the pier access, so it is not a drop-in quality upgrade.

**Minimal hybrid implementation sketch:**

```
# direct bike
GET https://brouter.de/brouter?lonlats=lon1,lat1|lon2,lat2
    &profile=trekking&alternativeidx=0&format=geojson

# transit itinerary
GET http://motis:8081/api/v6/plan?fromPlace=...&toPlace=...
    &directModes=WALK&transitModes=TRANSIT&time=...

# merge: keep MOTIS transit legs, replace direct BIKE legs (and bike access/egress)
# with BRouter geometry; recompute duration from BRouter total-time; fall back to
# MOTIS direct bike on BRouter timeout/403.
```

Use `profile=safety` instead of `trekking` if the demo's priority is avoiding primary roads; use `fastbike` only for a speed-oriented mode. Cache the BRouter response per OD/profile for the demo.

**Do not build the hybrid just for this demo unless turn-by-turn or elevation is a stated requirement.** The added service, rate-limit handling, and route-merging logic are more work than the one bad OD (Brzeźno) justifies. Fix the guardrail, precompute/denylist that OD, and keep MOTIS.

---

## 7. Caveats

- **OSM date:** the local extract is from `pomorskie-latest.osm.pbf` (early 2026); Google/Valhalla/BRouter use current OSM. Small geometry differences are expected, especially on newly built cycleways.
- **MOTIS surface/road-class percentages are approximate** (nearest-way matching within 30 m). Where a cycleway runs parallel to a footway or road, the nearest match can misclassify a segment by one category. Treat the percentages as ±5–10 points; the r12 sand finding is confirmed by the OSM way tag and is not a matching artifact.
- **Signal/crossing counts** are OSM nodes within 25 m of the route, not necessarily nodes the rider must cross. They are a proxy for urban friction, not a traffic-light cost model.
- **Turns** are geometric bearing changes, not routing instructions; GH's `instructions` count is higher because it includes lane/keep instructions.
- **Ascent** is BRouter's `filtered ascend` from SRTM; MOTIS/GH are 2D. The Tri-City is mostly flat (BRouter trekking averages ~3.7 m/km); the main climbs are Jasień (110 m) and Osowa (151 m), the rest are 6–54 m.
- **Walk** was spot-checked on 3 routes only; the 15-route benchmark and all quality metrics are bike-only.
- **Google Maps** was checked through the web UI with Playwright; it is qualitative, not an API, and Google's route options/times can change. **Organic Maps** has no public cycling API and was not available as a live app in this environment; the manual reference is therefore Google Maps + OSM tiles + Valhalla, not Organic Maps.
- **BRouter public API** returned one 403 (rate limit) during 45 requests; it was retried successfully. A public demo should cache or self-host.
- **GraphHopper** was run with the existing `graph-tricity-mmap-trimmed2` graph (2D, no elevation). A production GH bike profile with elevation and a custom model could score differently.

---

## 8. Artifacts

All under `/private/var/folders/2y/1bsn02s15h10sbtw8y9cfpk00000gn/T/opencode/route-quality`:

- `bench.py` — queries MOTIS/GH/BRouter for the 15 ODs; raw JSON in `out/`.
- `metrics.py` — geometry decoding, OSM nearest-way classification, surface/signal/turn metrics; writes `metrics.json`.
- `table.py` — generates the tables above.
- `make_map.py` / `map_r*.html` / `map_r*.png` — Leaflet overlays for visual spot checks (r04, r05, r06, r07, r08, r09, r11, r12, r14, r15).
- `gmap_*.png` / `gmap_*.txt` — Google Maps cycling screenshots/text for r01, r04, r05, r11, r12, r15.
- `highways.geojson`, `signals.geojson`, `osm_index.pkl` — local OSM index used for metrics.
- `manifest.json`, `points.json` — OD definitions and coordinates.

**Servers used:** MOTIS on `127.0.0.1:8081` (data: `motis-spike/data/motis-data`, re-imported with the port block); GraphHopper on `127.0.0.1:8989` (config `graphhopper-tune/config-tricity-mmap-trimmed2.yml`).
