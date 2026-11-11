#!/usr/bin/env python3
"""Trim a GTFS feed to a bounding box.

Keeps stops inside the bbox (plus their parent stations). For every trip it
keeps the longest *contiguous* run of stop_times at kept stops (>= 2 rows) and
drops the rest, so arrival/departure times stay monotonic. Trips, routes,
calendar entries and shapes are filtered to what is still referenced.

The default box covers the Tri-City area used by the MOTIS setup. Adjust the
constants below for a different service area.
"""
import csv
import io
import sys
import zipfile
from collections import defaultdict

LEFT, BOTTOM, RIGHT, TOP = 18.35, 54.25, 18.75, 54.55


def read_table(zf, name):
    if name not in zf.namelist():
        return None, None
    text = zf.read(name).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return reader.fieldnames, list(reader)


def main(src, dst):
    with zipfile.ZipFile(src) as zin:
        fields, stops = read_table(zin, "stops.txt")
        if stops is None:
            print(f"{src}: no stops.txt, skipping")
            return
        keep = set()
        for s in stops:
            try:
                lat, lon = float(s["stop_lat"]), float(s["stop_lon"])
            except (KeyError, ValueError):
                continue
            if BOTTOM <= lat <= TOP and LEFT <= lon <= RIGHT:
                keep.add(s["stop_id"])
        by_id = {s["stop_id"]: s for s in stops}
        for sid in list(keep):
            parent = by_id[sid].get("parent_station") or ""
            if parent:
                keep.add(parent)

        # group stop_times by trip, preserving original order
        st_fields = None
        rows_by_trip = defaultdict(list)
        if "stop_times.txt" in zin.namelist():
            text = zin.read("stop_times.txt").decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            st_fields = reader.fieldnames
            for row in reader:
                rows_by_trip[row["trip_id"]].append(row)

        out_rows = []
        kept_trips = set()
        for trip_id, rows in rows_by_trip.items():
            rows.sort(key=lambda r: int(r["stop_sequence"]))
            best, cur = [], []
            for row in rows:
                if row["stop_id"] in keep:
                    cur.append(row)
                else:
                    if len(cur) > len(best):
                        best = cur
                    cur = []
            if len(cur) > len(best):
                best = cur
            if len(best) >= 2:
                kept_trips.add(trip_id)
                for i, row in enumerate(best, start=1):
                    row["stop_sequence"] = str(i)
                    out_rows.append(row)

        trips_fields, trips = read_table(zin, "trips.txt")
        trips = [t for t in trips if t["trip_id"] in kept_trips]
        route_ids = {t["route_id"] for t in trips}
        service_ids = {t.get("service_id") for t in trips}
        shape_ids = {t.get("shape_id") for t in trips if t.get("shape_id")}

        routes_fields, routes = read_table(zin, "routes.txt")
        routes = [r for r in routes if r["route_id"] in route_ids]

        cal_fields, cal = read_table(zin, "calendar.txt")
        if cal is not None:
            cal = [c for c in cal if c["service_id"] in service_ids]
        cd_fields, cd = read_table(zin, "calendar_dates.txt")
        if cd is not None:
            cd = [c for c in cd if c["service_id"] in service_ids]

        sh_fields, shapes = read_table(zin, "shapes.txt")
        if shapes is not None:
            shapes = [s for s in shapes if s["shape_id"] in shape_ids]

        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
            def write(name, header, rows):
                if rows is None:
                    return
                buf = io.StringIO()
                w = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
                zout.writestr(name, buf.getvalue())

            write("stops.txt", fields, [s for s in stops if s["stop_id"] in keep])
            write("stop_times.txt", st_fields, out_rows)
            write("trips.txt", trips_fields, trips)
            write("routes.txt", routes_fields, routes)
            write("calendar.txt", cal_fields, cal)
            write("calendar_dates.txt", cd_fields, cd)
            write("shapes.txt", sh_fields, shapes)
            for extra in ("agency.txt", "feed_info.txt", "transfers.txt", "frequencies.txt"):
                if extra in zin.namelist():
                    zout.writestr(extra, zin.read(extra))

    print(f"{src} -> {dst}: stops={len(keep)} trips={len(kept_trips)} stop_times={len(out_rows)} routes={len(routes)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
