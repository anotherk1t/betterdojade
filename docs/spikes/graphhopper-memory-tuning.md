# GraphHopper memory tuning — Tri-City multimodal (OSM + 4 GTFS feeds)

Date: 2026-11-11
Work dir: `/private/var/folders/2y/1bsn02s15h10sbtw8y9cfpk00000gn/T/opencode/graphhopper-tune`
GraphHopper source: `/Users/yan/Documents/graphhopper` @ `ced830db0` (12.0-SNAPSHOT)
Nothing in `/Users/yan/Documents/bikerouter` was touched.

## TL;DR

**Yes — GraphHopper runs comfortably in 2–3 GB for this dataset.**

| Setup | Heap | Import wall | Import peak RSS | Graph on disk | Idle RSS | RSS after PT load | Live heap after GC |
|---|---|---|---|---|---|---|---|
| Full 4 GTFS feeds | `-Xms2g -Xmx2g` | 38.0 s | 4.53 GiB | 1001 MB | 2.29 GiB | 2.84 GiB | 1.18 GiB |
| GTFS trimmed to bbox | `-Xms2g -Xmx2g` | 34.0 s | 3.51 GiB | 730 MB | 1.92 GiB | 2.14 GiB | — |
| GTFS trimmed to bbox | `-Xms1536m -Xmx1536m` | — | — | — | 1.75 GiB | 1.98 GiB | — |
| GTFS trimmed to bbox | `-Xms1g -Xmx1g` | — | — | — | 1.27 GiB | 1.65 GiB | 0.84 GiB (80% of heap → GC thrash) |

No OOM at 2 GB. The 3 GB retry was not needed.
Import is the real peak: **~4.5 GiB RSS**, so build the graph on a box/CI job with ≥5 GB free.

Key finding: **the PT/GTFS data is 97 % of the graph.** The street graph for the
Tri-City extract is only 23 MB; the four GTFS feeds add 978 MB of `pt_edges`,
`pt_edge_attrs`, `pt_nodes`, serialized `GtfsStorage` (`gtfs_*.p`) etc. Memory
tuning for this setup is GTFS tuning, not OSM tuning.

## Environment

- macOS 27.2, arm64, 64 GB RAM
- OpenJDK 21.0.13 (Homebrew): `/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home`
  (no JDK was installed; `brew install openjdk@21`)
- Maven 3.9.6 bundled at `/Users/yan/Documents/graphhopper/apache-maven-3.9.6`
- osmium 1.19.1 (already present at `/opt/homebrew/bin/osmium`)
- GraphHopper built with `mvn -DskipTests package` → 79 s, 501 MB peak RSS,
  `web/target/graphhopper-web-12.0-SNAPSHOT.jar` (51 MB, includes `reader-gtfs`)

## 1. Tri-City OSM extract

```bash
osmium extract -b 18.35,54.25,18.75,54.55 --overwrite \
  -o tricity.osm.pbf /Users/yan/Documents/graphhopper/pomorskie-latest.osm.pbf
```

Result: **27 MB** PBF, 247,212 routable nodes / 330,976 edges after import
(2.7 M raw nodes, 399 k ways).

Note: osmium's default `complete_ways` strategy drags in whole ferry ways, so the
file bbox is `(15.57, 53.45, 20.35, 58.92)` — the graph reports bounds up to
58.9°N and accepts points far outside the Tri-City area. This does not affect
memory materially (`--strategy=simple` gives 2.67 M vs 2.70 M nodes), but if you
want a strict bbox you need a second clip or `--strategy=simple` plus
`osmium tags-filter` for `route=ferry`.

## 2. Config changes (`config-tricity-mmap.yml`)

Diff vs `/Users/yan/Documents/graphhopper/config-pt-with-bike.yml`:

```yaml
 graphhopper:
-  datareader.file: pomorskie-latest.osm.pbf
+  datareader.file: <workdir>/tricity.osm.pbf
-  gtfs.file: gtfs-gdansk.zip,gtfs-skm.zip,gtfs-polregio.zip,gtfs-gdynia.zip
+  gtfs.file: /Users/yan/Documents/graphhopper/gtfs-gdansk.zip,/Users/yan/Documents/graphhopper/gtfs-skm.zip,/Users/yan/Documents/graphhopper/gtfs-polregio.zip,/Users/yan/Documents/graphhopper/gtfs-gdynia.zip
-  graph.location: graphs/pomorskie-with-transit-bike
+  graph.location: <workdir>/graph-tricity-mmap
   profiles: foot, bike                      # unchanged, only these two
   graph.encoded_values: ...                 # unchanged
+  graph.dataaccess.default_type: MMAP
+  profiles_ch: []
+  profiles_lm: []
 server:
-  bind_host: 0.0.0.0
+  bind_host: 127.0.0.1                      # test-only
```

- No `graph.elevation.*` entries at all → 2D graph (`elevation: false` in `/info`).
- CH and LM explicitly empty. (The original config also had none, so this is
  documentation rather than a change in behaviour.)
- All four GTFS feeds imported successfully; none had to be dropped.

## 3. Import

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
/usr/bin/time -l $JAVA_HOME/bin/java -Xmx4g \
  -jar /Users/yan/Documents/graphhopper/web/target/graphhopper-web-12.0-SNAPSHOT.jar \
  import config-tricity-mmap.yml
```

| Metric | Full feeds | Trimmed feeds |
|---|---|---|
| Wall time | **37.96 s** (75.9 s user) | **34.04 s** (62.3 s user) |
| Peak RSS (`maximum resident set size`) | **4,859,052,032 B = 4.53 GiB** | 3,767,173,120 B = 3.51 GiB |
| Graph size | **1001 MB** (1,050,040,223 B) | 730 MB |
| Street part | 23 MB | 23 MB |
| PT part | 978 MB | 707 MB |

Import log highlights: OSM read 3 s, GTFS parsing ~16 s, transit graph build ~15 s,
flush ~3 s. Calendar range of the feeds: **2026-03-02 … 2026-03-15** (see caveats).

Largest files (full feeds): `pt_edges` 393 MB, `pt_edge_attrs` 250 MB,
`gtfs_0.p` (Gdańsk) 94 MB, `pt_nodes` 60 MB, `gtfs_1.p` (SKM) 56 MB,
`gtfs_3.p` (Gdynia) 49 MB, `gtfs_2.p` (Polregio) 33 MB.

## 4. Server

```bash
nohup $JAVA_HOME/bin/java -Xms2g -Xmx2g \
  -jar .../graphhopper-web-12.0-SNAPSHOT.jar server config-tricity-mmap.yml &
```

Startup ~4–7 s. `/info` reports profiles `foot`, `bike`, `pt`, `elevation: false`.

Full 4 feeds, `-Xms2g -Xmx2g` (`ps -o rss`):

| Point | RSS |
|---|---|
| Idle after startup | 2,400,896 KiB = **2.29 GiB** |
| After foot route | 2,410,912 KiB = 2.30 GiB |
| After bike route | 2,421,856 KiB = 2.31 GiB |
| After first PT route | 2,663,728 KiB = 2.54 GiB |
| After 8 sequential PT routes | 2,945,648 KiB = 2.81 GiB |
| After 6 concurrent PT routes | 2,973,248 KiB = **2.84 GiB** |

Heap after `jcmd GC.run`: **1,240,248 KiB used of 2,097,152 KiB (1.18 GiB)**.
No `OutOfMemoryError` in the log; 6 parallel PT queries all returned 200 in
0.65–1.06 s.

Trimmed feeds: idle 1.92 GiB, 2.14 GiB after PT at 2g; 1.75 / 1.98 GiB at
`-Xmx1536m`; 1.27 / 1.65 GiB at `-Xmx1g`. At 1g the heap sits at 96 % after a
query and PT latency roughly doubles (1.4–1.6 s vs 0.5 s) — 1 GB is the floor,
not a recommendation.

RSS includes mmap'd graph pages (clean, reclaimable page cache). The
non-reclaimable part is roughly heap live set + metaspace (~42 MB) + JVM
overhead. In a cgroup this means the 2.84 GiB figure is a soft ceiling, not a
hard requirement.

## 5. Route queries

| Query | HTTP | Result |
|---|---|---|
| foot, Gdańsk Główny → Wrzeszcz | **200** | 4,228.7 m, 51 min, 123 points, 58 ms |
| bike, Gdańsk Główny → Gdynia Główna | **200** | 22,285.1 m, 82 min, 617 points, 108 ms |
| PT, Gdańsk Główny → Gdynia Główna, dep 2026-03-03T08:00Z | **200** | 721 m total, 53.6 min, legs `walk 189 m → pt 08:24–08:47 → walk 531 m`, 427 ms, 196,870 visited nodes |

The PT response is a real SKM itinerary (trip `T-50691-05-8P-R-1-0-2026-12`),
not a walk-only fallback. The same itinerary is produced by the trimmed feeds.

Example:
```bash
curl 'http://127.0.0.1:8989/route?profile=pt&point=54.3556,18.6440&point=54.5180,18.5310&pt.earliest_departure_time=2026-03-03T08:00:00Z'
```
(GraphHopper point order is **lat,lon**.)

## 6. Verdict

- **2 GB heap is enough** for the full Tri-City OSM + all four GTFS feeds.
  Expect ~2.3 GiB RSS idle and ~2.8–2.9 GiB after PT traffic. Recommend a
  **3 GB container** (2g heap + JVM native + page cache) for production.
- **Import needs ~4.5 GiB RSS** — run it with `-Xmx4g` on a machine with 5–6 GB
  free, or import at build time and ship the graph directory.
- **GTFS is the cost driver**, and mostly the Gdańsk city feed: 2.19 M of the
  3.32 M total stop_times rows, of which 2.13 M survive the bbox filter because
  the bbox covers most of Gdańsk. Polregio drops from 857 k to 54 k rows,
  Gdynia from 237 k to 180 k, SKM from 39 k to 29 k. Trimming all four feeds
  removes ~0.93 M stop_times (28 %) and cuts the graph from 1001 → 730 MB and
  the live heap from 1.18 → 0.86 GiB; then `-Xmx1536m` is comfortable and
  `-Xmx1g` becomes possible (but slow).
- Disabling CH/LM is the right call: the street graph is 23 MB, so preparation
  would add little value and only cost import time/RAM.
- If you need to go below 2 GB, the lever is GTFS filtering, not JVM flags.

## Caveats

- The GTFS feeds' service window is **2026-03-02 … 2026-03-15** (March data,
  imported in November). PT queries must use a date in that window; with a
  current date GraphHopper will return walk-only results. Refresh the feeds
  before production.
- The bbox trimmer (`trim_gtfs.py`) keeps the longest contiguous in-bbox segment
  of each trip. It is good enough for a memory experiment and produced sane
  itineraries, but it is not a general GTFS validator (no shape interpolation,
  no frequency-based trips, no transfers.txt handling).
- The `-Xmx1536m` run was stopped by the shell session after measurement, not by
  an OOM; the 2g run was exercised across many separate commands.
- All numbers are from a 64 GB Apple-silicon Mac; Linux RSS will differ somewhat,
  mostly in mmap accounting.

## Artifacts

- `config-tricity-mmap.yml` — full 4-feed config
- `config-tricity-mmap-trimmed2.yml` — bbox-trimmed GTFS config
- `tricity.osm.pbf` — 27 MB extract
- `graph-tricity-mmap/` (1001 MB), `graph-tricity-mmap-trimmed2/` (730 MB)
- `import.log`, `import.time.log`, `import-trimmed2.log`, `server-2g.log`,
  `server-trimmed2-*.log`
- `trim_gtfs.py` — bbox GTFS trimmer
