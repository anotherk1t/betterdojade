#!/usr/bin/env python3
"""Compute route quality metrics from saved MOTIS/GH/BRouter responses."""
import json, math, os, pickle, sys

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "out")
CACHE = os.path.join(BASE, "osm_index.pkl")

R = 6371008.8


def hav(a, b):
    lon1, lat1 = a; lon2, lat2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(min(1, math.sqrt(h)))


def plen(coords):
    return sum(hav(coords[i], coords[i + 1]) for i in range(len(coords) - 1))


def resample(coords, step=10.0):
    """Resample a polyline at approximately `step` metres."""
    if not coords:
        return []
    out = [coords[0]]
    carry = 0.0
    for i in range(len(coords) - 1):
        a, b = coords[i], coords[i + 1]
        d = hav(a, b)
        if d == 0:
            continue
        t = (step - carry) / d
        while t <= 1.0:
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            t += step / d
        carry = (1.0 - (t - step / d)) * d
    if out[-1] != coords[-1]:
        out.append(coords[-1])
    return out


def decode(s, factor=1e6):
    coords = []; lat = lon = 0; i = 0
    while i < len(s):
        vals = []
        for _ in range(2):
            shift = 0; result = 0
            while True:
                b = ord(s[i]) - 63; i += 1
                result |= (b & 0x1f) << shift; shift += 5
                if b < 0x20:
                    break
            vals.append(~(result >> 1) if result & 1 else (result >> 1))
        lat += vals[0]; lon += vals[1]
        coords.append((lon / factor, lat / factor))
    return coords


def bearing(a, b):
    lon1, lat1 = map(math.radians, a); lon2, lat2 = map(math.radians, b)
    dl = lon2 - lon1
    y = math.sin(dl) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dl)
    return math.degrees(math.atan2(y, x))


def angle_diff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def count_turns(coords, min_angle=32.0, min_spacing=18.0):
    """Geometric turn count: significant bearing changes, merged when close."""
    pts = resample(coords, 8.0)
    if len(pts) < 3:
        return 0
    # smooth with a 15 m look-back
    turns = 0
    last_turn_pos = -1e9
    dist = 0.0
    for i in range(1, len(pts) - 1):
        d = hav(pts[i - 1], pts[i])
        dist += d
        if dist - last_turn_pos < min_spacing:
            continue
        b1 = bearing(pts[max(0, i - 2)], pts[i])
        b2 = bearing(pts[i], pts[min(len(pts) - 1, i + 2)])
        if angle_diff(b1, b2) >= min_angle:
            turns += 1
            last_turn_pos = dist
    return turns


# ------------------------- OSM index -------------------------

def build_index():
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    print("building OSM index...", file=sys.stderr)
    d = json.load(open(os.path.join(BASE, "highways.geojson")))
    ways = []
    segs = []  # (x1,y1,x2,y2, way_idx, cx, cy)
    CELL = 0.002
    grid = {}
    for f in d["features"]:
        if f["geometry"]["type"] != "LineString":
            continue
        p = f["properties"]
        hw = p.get("highway")
        if not hw:
            continue
        ways.append({
            "highway": hw,
            "name": p.get("name", ""),
            "surface": p.get("surface", ""),
            "bicycle": p.get("bicycle", ""),
            "cycleway": p.get("cycleway", ""),
            "cycleway_left": p.get("cycleway:left", ""),
            "cycleway_right": p.get("cycleway:right", ""),
            "foot": p.get("foot", ""),
        })
        wi = len(ways) - 1
        cs = f["geometry"]["coordinates"]
        for i in range(len(cs) - 1):
            x1, y1 = cs[i]; x2, y2 = cs[i + 1]
            si = len(segs)
            segs.append((x1, y1, x2, y2, wi))
            # index into every cell the segment bbox touches
            for cx in range(int(min(x1, x2) / CELL), int(max(x1, x2) / CELL) + 1):
                for cy in range(int(min(y1, y2) / CELL), int(max(y1, y2) / CELL) + 1):
                    grid.setdefault((cx, cy), []).append(si)
    data = {"ways": ways, "segs": segs, "grid": grid, "cell": CELL}
    with open(CACHE, "wb") as f:
        pickle.dump(data, f, protocol=4)
    return data


IDX = None


def nearest_way(pt):
    global IDX
    if IDX is None:
        IDX = build_index()
    x, y = pt
    CELL = IDX["cell"]; grid = IDX["grid"]; segs = IDX["segs"]; ways = IDX["ways"]
    cx, cy = int(x / CELL), int(y / CELL)
    best = None; bestd = 1e9
    coslat = math.cos(math.radians(y))
    for gx in range(cx - 1, cx + 2):
        for gy in range(cy - 1, cy + 2):
            for si in grid.get((gx, gy), ()):
                x1, y1, x2, y2, wi = segs[si]
                # local metric coordinates
                px = (x - x1) * 111320 * coslat; py = (y - y1) * 110540
                vx = (x2 - x1) * 111320 * coslat; vy = (y2 - y1) * 110540
                vv = vx * vx + vy * vy
                t = 0.0 if vv == 0 else max(0.0, min(1.0, (px * vx + py * vy) / vv))
                dx = px - t * vx; dy = py - t * vy
                dd = dx * dx + dy * dy
                if dd < bestd:
                    bestd = dd; best = wi
    if best is None:
        return None, 1e9
    return ways[best], math.sqrt(bestd)


CYCLE_HW = {"cycleway", "path", "track", "bridleway", "footway", "pedestrian", "living_street"}
MAJOR_HW = {"trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link"}
MINOR_HW = {"tertiary", "tertiary_link", "residential", "unclassified", "service", "road"}
OFFROAD_HW = {"cycleway", "path", "track", "bridleway"}


def classify(tags):
    hw = tags.get("highway", "")
    bike = tags.get("bicycle", "")
    cwvals = [tags.get(k, "") for k in ("cycleway", "cycleway_left", "cycleway_right")]
    has_cw = any(v not in ("", "no", "none", "separate", "unknown") for v in cwvals)
    if hw in OFFROAD_HW or bike in ("designated", "official") or has_cw:
        return "cycle"
    if hw in MAJOR_HW:
        return "major"
    if hw in ("footway", "pedestrian", "living_street", "steps"):
        return "foot"
    if hw in MINOR_HW:
        return "minor"
    return "other"


def classify_br(tagstr):
    tags = {}
    for kv in tagstr.split():
        if "=" in kv:
            k, v = kv.split("=", 1)
            tags[k] = v
    # BRouter uses e.g. highway=cycleway, bicycle=designated, cycleway=lane
    return classify(tags)


def classify_surface(surf):
    s = (surf or "").lower()
    if s in ("asphalt", "paved", "concrete", "concrete:plates", "concrete:lanes", "paving_stones"):
        return "paved"
    if s in ("sett", "cobblestone", "unhewn_cobblestone", "bricks"):
        return "cobble"
    if s in ("", "unknown"):
        return "unknown"
    return "unpaved"


def pct_from_assignments(items):
    """items: list of (length, category)"""
    tot = sum(l for l, _ in items)
    out = {}
    for c in ("cycle", "major", "foot", "minor", "other", "unknown", "paved", "unpaved", "cobble"):
        s = sum(l for l, cc in items if cc == c)
        out[c] = 100.0 * s / tot if tot else 0.0
    out["total"] = tot
    return out


def motis_metrics(path):
    d = json.load(open(path))
    if not d["raw"].get("direct"):
        return None
    it = d["raw"]["direct"][0]
    leg = it["legs"][0]
    coords = decode(leg["legGeometry"]["points"])
    items = []; sitems = []
    for i in range(len(coords) - 1):
        a, b = coords[i], coords[i + 1]
        L = hav(a, b)
        if L < 0.5:
            continue
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        w, dist = nearest_way(mid)
        items.append((L, classify(w) if w and dist <= 30 else "unknown"))
        sitems.append((L, classify_surface(w.get("surface")) if w and dist <= 30 else "unknown"))
    m = pct_from_assignments(items)
    sm = pct_from_assignments(sitems)
    m.update({
        "distance": leg["distance"],
        "duration": it["duration"],
        "geom_len": plen(coords),
        "turns": count_turns(coords),
        "surf_paved": sm["paved"], "surf_unpaved": sm["unpaved"], "surf_cobble": sm["cobble"], "surf_unknown": sm["unknown"],
        "snap_start": hav(coords[0], (d["raw"]["from"]["lon"], d["raw"]["from"]["lat"])),
        "snap_end": hav(coords[-1], (d["raw"]["to"]["lon"], d["raw"]["to"]["lat"])),
        "coords": coords,
    })
    return m


def gh_metrics(path):
    d = json.load(open(path))
    if "paths" not in d or not d["paths"]:
        return None
    p = d["paths"][0]
    coords = [(x, y) for x, y in p["points"]["coordinates"]]
    seglen = [hav(coords[i], coords[i + 1]) for i in range(len(coords) - 1)]
    items = []
    det = p["details"].get("road_class", [])
    for lo, hi, val in det:
        L = sum(seglen[lo:hi])
        fake = {"highway": val}
        items.append((L, classify(fake)))
    m = pct_from_assignments(items)
    sitems = []
    for lo, hi, val in p["details"].get("surface", []):
        sitems.append((sum(seglen[lo:hi]), classify_surface(val)))
    sm = pct_from_assignments(sitems)
    m.update({
        "distance": p["distance"],
        "duration": p["time"] / 1000.0,
        "geom_len": plen(coords),
        "turns": count_turns(coords),
        "instr": len(p.get("instructions", [])),
        "surf_paved": sm["paved"], "surf_unpaved": sm["unpaved"], "surf_cobble": sm["cobble"], "surf_unknown": sm["unknown"],
        "ascend": p.get("ascend"),
        "coords": coords,
    })
    return m


def br_metrics(path):
    d = json.load(open(path))
    f = d["features"][0]
    props = f["properties"]
    coords = [(x, y) for x, y, *rest in f["geometry"]["coordinates"]]
    msgs = props.get("messages", [])
    hdr = msgs[0] if msgs else []
    try:
        i_dist = hdr.index("Distance"); i_tags = hdr.index("WayTags")
        i_turn = hdr.index("TurnCost"); i_elev = hdr.index("Elevation")
    except ValueError:
        i_dist, i_tags, i_turn, i_elev = 3, 9, 6, 2
    items = []; sitems = []
    turns = 0
    for row in msgs[1:]:
        L = float(row[i_dist])
        items.append((L, classify_br(row[i_tags])))
        st = {}
        for kv in row[i_tags].split():
            if "=" in kv:
                k, v = kv.split("=", 1); st[k] = v
        sitems.append((L, classify_surface(st.get("surface", ""))))
        if float(row[i_turn]) > 0:
            turns += 1
    m = pct_from_assignments(items)
    sm = pct_from_assignments(sitems)
    m.update({
        "distance": float(props["track-length"]),
        "duration": float(props["total-time"]),
        "geom_len": plen(coords),
        "turns": count_turns(coords),
        "br_turns": turns,
        "surf_paved": sm["paved"], "surf_unpaved": sm["unpaved"], "surf_cobble": sm["cobble"], "surf_unknown": sm["unknown"],
        "ascend": float(props.get("filtered ascend", 0)),
        "coords": coords,
    })
    return m


def count_near(coords, points, radius=25.0):
    from collections import defaultdict
    CELL = 0.0015
    grid = defaultdict(list)
    for (x, y) in points:
        grid[(int(x / CELL), int(y / CELL))].append((x, y))
    pts = resample(coords, 12.0)
    seen = set()
    for q in pts:
        cx, cy = int(q[0] / CELL), int(q[1] / CELL)
        for gx in range(cx - 1, cx + 2):
            for gy in range(cy - 1, cy + 2):
                for (x, y) in grid.get((gx, gy), ()):
                    if hav(q, (x, y)) <= radius:
                        seen.add((round(x, 6), round(y, 6)))
    return len(seen)


def overlap(coords_a, coords_b, tol=30.0):
    """% of A's samples within tol of B."""
    from collections import defaultdict
    CELL = 0.002
    grid = defaultdict(list)
    for i in range(len(coords_b) - 1):
        x1, y1 = coords_b[i]; x2, y2 = coords_b[i + 1]
        for cx in range(int(min(x1, x2) / CELL), int(max(x1, x2) / CELL) + 1):
            for cy in range(int(min(y1, y2) / CELL), int(max(y1, y2) / CELL) + 1):
                grid[(cx, cy)].append(i)
    ok = 0; tot = 0
    for q in resample(coords_a, 15.0):
        tot += 1
        cx, cy = int(q[0] / CELL), int(q[1] / CELL)
        best = 1e9
        for gx in range(cx - 1, cx + 2):
            for gy in range(cy - 1, cy + 2):
                for i in grid.get((gx, gy), ()):
                    a, b = coords_b[i], coords_b[i + 1]
                    # point-seg
                    coslat = math.cos(math.radians(q[1]))
                    px = (q[0] - a[0]) * 111320 * coslat; py = (q[1] - a[1]) * 110540
                    vx = (b[0] - a[0]) * 111320 * coslat; vy = (b[1] - a[1]) * 110540
                    vv = vx * vx + vy * vy
                    t = 0 if vv == 0 else max(0, min(1, (px * vx + py * vy) / vv))
                    dd = math.hypot(px - t * vx, py - t * vy)
                    if dd < best: best = dd
        if best <= tol:
            ok += 1
    return 100.0 * ok / tot if tot else 0.0


if __name__ == "__main__":
    man = json.load(open(os.path.join(BASE, "manifest.json")))
    signals = [(f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1])
               for f in json.load(open(os.path.join(BASE, "signals.geojson")))["features"]
               if f["properties"].get("highway") == "traffic_signals"]
    crossings = [(f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1])
                 for f in json.load(open(os.path.join(BASE, "signals.geojson")))["features"]
                 if f["properties"].get("highway") == "crossing"]

    results = {}
    for rec in man["routes"]:
        rid = rec["id"]
        r = {"name": rec["name"]}
        m = motis_metrics(os.path.join(OUT, f"{rid}_motis.json"))
        g = gh_metrics(os.path.join(OUT, f"{rid}_gh.json"))
        brs = {}
        for prof in ("trekking", "fastbike", "safety"):
            p = os.path.join(OUT, f"{rid}_br_{prof}.json")
            if os.path.exists(p):
                try:
                    brs[prof] = br_metrics(p)
                except Exception as e:
                    print(rid, prof, "ERR", e, file=sys.stderr)
        for name, mm in [("motis", m), ("gh", g)] + list(brs.items()):
            if mm:
                mm["signals"] = count_near(mm["coords"], signals)
                mm["crossings"] = count_near(mm["coords"], crossings)
        if m and brs.get("trekking"):
            m["overlap_br"] = overlap(m["coords"], brs["trekking"]["coords"], 30)
        for name, mm in [("motis", m), ("gh", g)] + list(brs.items()):
            if mm:
                mm.pop("coords", None)
        r.update({"motis": m, "gh": g, "br": brs})
        results[rid] = r
        print(rid, rec["name"])
        for k in ("motis", "gh", "trekking", "fastbike", "safety"):
            mm = m if k == "motis" else g if k == "gh" else brs.get(k)
            if not mm:
                print(f"   {k:9s} FAILED"); continue
            print(f"   {k:9s} {mm['distance']/1000:6.2f} km {mm['duration']/60:5.1f} min "
                  f"cycle {mm['cycle']:4.0f}% major {mm['major']:4.0f}% foot {mm['foot']:3.0f}% "
                  f"minor {mm['minor']:3.0f}% unk {mm['unknown']:3.0f}% turns {mm['turns']:3d} "
                  f"sig {mm['signals']:2d} cross {mm['crossings']:2d} "
                  f"paved {mm['surf_paved']:3.0f}% unpaved {mm['surf_unpaved']:3.0f}% cobble {mm['surf_cobble']:3.0f}%"
                  + (f" asc {mm.get('ascend'):.0f}" if mm.get("ascend") is not None else "")
                  + (f" overlap {m.get('overlap_br',0):.0f}%" if k == "motis" else ""))
    json.dump(results, open(os.path.join(BASE, "metrics.json"), "w"), indent=1)
    print("\nwrote metrics.json")
