#!/usr/bin/env python3
"""Query MOTIS, GraphHopper and BRouter for the Tri-City benchmark routes."""
import json, os, time, urllib.parse, urllib.request, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "out")
os.makedirs(OUT, exist_ok=True)

MOTIS_URL = os.environ.get("MOTIS_URL", "http://127.0.0.1:8081")
GH_URL = os.environ.get("GH_URL", "http://127.0.0.1:8989")
BROUTER_URL = os.environ.get("BROUTER_URL", "https://brouter.de/brouter")

with open(os.path.join(BASE, "points.json")) as f:
    P = {name: (p["lat"], p["lon"]) for name, p in json.load(f).items()}

ROUTES = [
    ("r01", "Gdansk Glowny -> Stare Miasto", "gdansk_glowny", "stare_miasto"),
    ("r02", "Gdansk Glowny -> Wrzeszcz", "gdansk_glowny", "wrzeszcz"),
    ("r03", "Gdansk Glowny -> Oliwa", "gdansk_glowny", "oliwa"),
    ("r04", "Gdansk Glowny -> Sopot", "gdansk_glowny", "sopot"),
    ("r05", "Gdansk Glowny -> Gdynia Glowna", "gdansk_glowny", "gdynia_glowna"),
    ("r06", "Wrzeszcz -> Oliwa (hilly)", "wrzeszcz", "oliwa"),
    ("r07", "Oliwa -> Sopot (hilly)", "oliwa", "sopot"),
    ("r08", "Sopot -> Gdynia", "sopot", "gdynia_glowna"),
    ("r09", "Gdansk Glowny -> Przymorze", "gdansk_glowny", "przymorze"),
    ("r10", "Gdansk Glowny -> Zaspa", "gdansk_glowny", "zaspa"),
    ("r11", "Gdansk Glowny -> Nowy Port", "gdansk_glowny", "nowy_port"),
    ("r12", "Gdansk Glowny -> Brzezno", "gdansk_glowny", "brzezno"),
    ("r13", "Gdansk Glowny -> Orunia", "gdansk_glowny", "orunia"),
    ("r14", "Gdansk Glowny -> Jasien", "gdansk_glowny", "jasien"),
    ("r15", "Gdansk Glowny -> Osowa", "gdansk_glowny", "osowa"),
]

UA = "route-quality-benchmark/1.0 (research; contact: local)"


def get(url, timeout=90, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(2 + 3 * i)
    raise last


def motis(route_id, a, b):
    lat1, lon1 = P[a]; lat2, lon2 = P[b]
    q = urllib.parse.urlencode({
        "fromPlace": f"{lat1},{lon1}",
        "toPlace": f"{lat2},{lon2}",
        "time": "2026-11-11T12:00:00+01:00",
        "directModes": "BIKE",
        "transitModes": "",
        "maxMatchingDistance": "250",
        "maxDirectTime": "14400",
    })
    url = f"{MOTIS_URL}/api/v6/plan?{q}"
    raw = get(url)
    data = json.loads(raw)
    n = len(data.get("direct") or [])
    # Diagnostic retry with a looser snap radius if the strict query fails.
    diag = None
    if n == 0:
        q2 = q.replace("maxMatchingDistance=250", "maxMatchingDistance=2000")
        try:
            diag = json.loads(get(f"{MOTIS_URL}/api/v6/plan?{q2}"))
        except Exception as e:
            diag = {"error": str(e)}
    return {"raw": data, "diag": diag, "n": n}


def gh(a, b):
    lat1, lon1 = P[a]; lat2, lon2 = P[b]
    parts = [
        "profile=bike",
        f"point={lat1},{lon1}",
        f"point={lat2},{lon2}",
        "points_encoded=false",
        "type=json",
    ]
    for d in ("road_class", "surface", "bike_network", "get_off_bike"):
        parts.append("details=" + d)
    url = GH_URL + "/route?" + "&".join(parts)
    return json.loads(get(url))


def brouter(a, b, profile):
    lat1, lon1 = P[a]; lat2, lon2 = P[b]
    url = (BROUTER_URL + "?lonlats="
           f"{lon1},{lat1}|{lon2},{lat2}&profile={profile}&alternativeidx=0&format=geojson")
    return json.loads(get(url))


def main():
    manifest = {"points": P, "routes": []}
    for rid, name, a, b in ROUTES:
        rec = {"id": rid, "name": name, "from": a, "to": b, "engines": {}}
        print(f"[{rid}] {name}", flush=True)

        try:
            m = motis(rid, a, b)
            json.dump(m, open(os.path.join(OUT, f"{rid}_motis.json"), "w"))
            rec["engines"]["motis"] = {"ok": m["n"] > 0, "n": m["n"],
                                       "diag_ok": bool(m["diag"] and m["diag"].get("direct"))}
            print(f"  motis: {m['n']} direct", flush=True)
        except Exception as e:
            rec["engines"]["motis"] = {"ok": False, "error": str(e)}
            print(f"  motis ERROR {e}", flush=True)

        try:
            g = gh(a, b)
            json.dump(g, open(os.path.join(OUT, f"{rid}_gh.json"), "w"))
            ok = "paths" in g and len(g["paths"]) > 0
            rec["engines"]["gh"] = {"ok": ok}
            if ok:
                p = g["paths"][0]
                print(f"  gh: {p['distance']:.0f} m {p['time']/60000:.1f} min", flush=True)
            else:
                print(f"  gh: no path {str(g)[:150]}", flush=True)
        except Exception as e:
            rec["engines"]["gh"] = {"ok": False, "error": str(e)}
            print(f"  gh ERROR {e}", flush=True)

        for prof in ("trekking", "fastbike", "safety"):
            try:
                br = brouter(a, b, prof)
                json.dump(br, open(os.path.join(OUT, f"{rid}_br_{prof}.json"), "w"))
                f = br["features"][0]["properties"]
                rec["engines"]["br_" + prof] = {"ok": True,
                                                "dist": float(f["track-length"]),
                                                "time": float(f["total-time"])}
                print(f"  br/{prof}: {f['track-length']} m {float(f['total-time'])/60:.1f} min", flush=True)
            except Exception as e:
                rec["engines"]["br_" + prof] = {"ok": False, "error": str(e)}
                print(f"  br/{prof} ERROR {e}", flush=True)
            time.sleep(0.7)

        manifest["routes"].append(rec)
        json.dump(manifest, open(os.path.join(BASE, "manifest.json"), "w"), indent=1)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
