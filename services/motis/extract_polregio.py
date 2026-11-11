#!/usr/bin/env python3
"""Extract the Polregio (agency_id PR) subset from mkuran.pl polish_trains.zip.

Usage: python3 extract_polregio.py polish-trains.zip gtfs-polregio-current.zip
"""
import csv
import io
import sys
import zipfile


def main(src, dst, agency="PR"):
    zin = zipfile.ZipFile(src)

    def read(name):
        return list(csv.DictReader(io.StringIO(zin.read(name).decode("utf-8-sig"))))

    routes_all = read("routes.txt")
    route_ids = {r["route_id"] for r in routes_all if r["agency_id"] == agency}
    trips = [t for t in read("trips.txt") if t["route_id"] in route_ids]
    trip_ids = {t["trip_id"] for t in trips}
    service_ids = {t["service_id"] for t in trips}
    shape_ids = {t["shape_id"] for t in trips if t.get("shape_id")}

    stop_times = [r for r in read("stop_times.txt") if r["trip_id"] in trip_ids]
    stops = read("stops.txt")
    used = {r["stop_id"] for r in stop_times}
    by_id = {s["stop_id"]: s for s in stops}
    for sid in list(used):
        parent = by_id.get(sid, {}).get("parent_station") or ""
        if parent:
            used.add(parent)
    stops = [s for s in stops if s["stop_id"] in used]
    routes = [r for r in routes_all if r["route_id"] in route_ids]
    calendar = (
        [c for c in read("calendar.txt") if c["service_id"] in service_ids]
        if "calendar.txt" in zin.namelist()
        else None
    )
    calendar_dates = (
        [c for c in read("calendar_dates.txt") if c["service_id"] in service_ids]
        if "calendar_dates.txt" in zin.namelist()
        else None
    )
    shapes = (
        [s for s in read("shapes.txt") if s["shape_id"] in shape_ids]
        if "shapes.txt" in zin.namelist()
        else None
    )
    agencies = [a for a in read("agency.txt") if a["agency_id"] == agency]

    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        def write(name, rows):
            if rows is None:
                return
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
            zout.writestr(name, buf.getvalue())

        write("agency.txt", agencies)
        write("stops.txt", stops)
        write("stop_times.txt", stop_times)
        write("trips.txt", trips)
        write("routes.txt", routes)
        write("calendar.txt", calendar)
        write("calendar_dates.txt", calendar_dates)
        write("shapes.txt", shapes)
        for extra in ("feed_info.txt", "transfers.txt", "attributions.txt"):
            if extra in zin.namelist():
                zout.writestr(extra, zin.read(extra))

    print(
        f"{src} -> {dst}: routes={len(routes)} trips={len(trips)} "
        f"stops={len(stops)} stop_times={len(stop_times)}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2])
