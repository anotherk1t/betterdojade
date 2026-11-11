#!/usr/bin/env python3
"""
Live delay-prediction service (runs on the collector .129).

Reads the freshest departures_*.json.gz the collector writes (~every 90s), maintains
an online per-departure history (windowed: events evicted once their departure passes),
predicts each upcoming departure's FINAL delay with the exported full-history model,
and serves it as JSON for the live page (model prediction vs ZTM's current delay).

Stdlib only (+ numpy, lightgbm). No framework deps. Bind to localhost; expose via the
existing cloudflared tunnel ingress.

  python3 delay_service.py --models <dir> --estimations <dir> --port 8091

Endpoints:
  GET /healthz      -> {"ok":true,"events":N,"last_snapshot":ts}
  GET /predictions  -> {"generated":ts,"count":N,"predictions":[...]}  (CORS: *)

CAVEAT: the model's `obs_total` feature is the FINAL observation count, unknown while a
trip is still upcoming; online we approximate it with the current count. Live MAE will
therefore be modestly worse than the offline backtest. Noted for a future history-free retrain.
"""

import argparse
import glob
import gzip
import json
import math
import os
import threading
import time
import urllib.request
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import lightgbm as lgb

# --- minimal inlined helpers (avoid importing the trainer, which pulls in xgboost) ---
GDANSK_ROUTES = {
    '10', '100', '106', '107', '108', '11', '110', '111', '112', '113', '115', '116', '117', '118',
    '12', '120', '122', '123', '124', '126', '127', '130', '131', '132', '136', '138', '143', '148',
    '149', '154', '155', '156', '157', '158', '162', '166', '167', '168', '169', '171', '174', '175',
    '176', '178', '179', '183', '184', '186', '189', '195', '199', '2', '200', '205', '207', '208',
    '210', '212', '213', '227', '232', '255', '256', '258', '262', '267', '268', '269', '283', '289',
    '295', '3', '307', '4', '5', '512', '6', '7', '8', '9', '911',
    'N1', 'N14', 'N16', 'N2', 'N3', 'N4', 'N5', 'N6', 'N78', 'N8', 'N89', 'N9', 'T8',
}
MIDNIGHT_S = 79200
MAX_CORR_S = 7200
# Above this |current_delay| the model under-predicts (regresses extremes to the mean);
# ground-truth retrospective showed it loses to ZTM only beyond ~1200s -> passthrough there.
GATE_DELAY_S = 1200
STOPS_URL = 'https://ckan2.multimediagdansk.pl/stops?date={date}'


def normalize_delay(d):
    if d is None:
        return None
    try:
        d = float(d)
    except (TypeError, ValueError):
        return None
    if abs(d) > MIDNIGHT_S:
        c = d - 86400 if d > 0 else d + 86400
        return c if abs(c) <= MAX_CORR_S else None
    return d


def parse_iso(s):
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
    except (ValueError, AttributeError, TypeError):
        return None


class Predictor:
    """Loads model + encoders, assembles a feature row, predicts."""

    def __init__(self, models_dir, which='fullhist'):
        meta = json.load(open(os.path.join(models_dir, 'tree_delay_encoders.json')))
        self.enc = meta['encoders']
        self.unk = meta['unk_index']
        self.feats = meta['feature_cols'][which]
        self.booster = lgb.Booster(model_file=os.path.join(models_dir, f'delay_{which}_model.txt'))

    def _code(self, col, val):
        return self.enc[col].get(str(val), self.unk[col])

    def features(self, route, stop_id, vsvc, headsign, hist, theo_ts, now):
        cur = hist[-1]
        prev1 = hist[-2] if len(hist) >= 2 else cur
        prev2 = hist[-3] if len(hist) >= 3 else prev1
        last3 = hist[-3:]
        dt = datetime.fromtimestamp(now, tz=timezone.utc)
        hour, dow = dt.hour, dt.weekday()
        f = {
            'route_enc': self._code('route', route),
            'stop_id_enc': self._code('stop_id', stop_id),
            'vehicle_service_enc': self._code('vehicle_service', vsvc),
            'headsign_enc': self._code('headsign', headsign),
            'lead_time_min': (theo_ts - now) / 60.0,
            'hour': hour, 'dow': dow,
            'hour_sin': math.sin(2 * math.pi * hour / 24), 'hour_cos': math.cos(2 * math.pi * hour / 24),
            'dow_sin': math.sin(2 * math.pi * dow / 7), 'dow_cos': math.cos(2 * math.pi * dow / 7),
            'current_delay': cur, 'prev1_delay': prev1, 'prev2_delay': prev2,
            'delta_prev1': cur - prev1, 'delta_prev2': prev1 - prev2,
            'hist_mean3': float(np.mean(last3)), 'hist_std3': float(np.std(last3)) if len(last3) > 1 else 0.0,
            'obs_index': len(hist) - 1, 'obs_total': len(hist),  # obs_total approximated online
        }
        return np.array([[f[c] for c in self.feats]], dtype=np.float32)


class Store:
    """Online windowed event history + current predictions snapshot."""

    def __init__(self, estimations_dir, predictor, poll_s=60):
        self.dir = estimations_dir
        self.pred = predictor
        self.poll_s = poll_s
        self.events = {}          # event_key -> {'meta':(route,stop,vsvc,headsign,theo_ts), 'hist':[delays]}
        self.snapshot = {'generated': 0, 'count': 0, 'predictions': []}
        self.last_file_ts = 0
        self.stop_names = {}      # stopId(str) -> human name ("Dąbrowa Centrum 04")
        self.stops_date = None
        self.lock = threading.Lock()

    def load_stops(self):
        """Load stopId -> name map from ZTM /stops (no-op if already loaded for today)."""
        today = date.today().isoformat()
        if self.stops_date == today and self.stop_names:
            return
        try:
            with urllib.request.urlopen(STOPS_URL.format(date=today), timeout=20) as r:
                data = json.loads(r.read())
            m = {}
            for s in data.get('stops', []):
                name, code = s.get('stopName') or '', s.get('stopCode')
                m[str(s.get('stopId'))] = f'{name} {code}'.strip() if code else name
            if m:
                self.stop_names, self.stops_date = m, today
                print(f'[stops] loaded {len(m)} stop names for {today}', flush=True)
        except Exception as e:
            print(f'[stops] load failed: {e}', flush=True)

    def _files_by_ts(self):
        out = []
        for f in glob.glob(os.path.join(self.dir, 'departures_*.json*')):
            stem = os.path.basename(f).replace('.json.gz', '').replace('.json', '')
            try:
                out.append((int(stem.split('_')[-1]) / 1000.0, f))
            except ValueError:
                continue
        return sorted(out)

    def _newest_file(self):
        fs = self._files_by_ts()
        return (fs[-1][1], fs[-1][0]) if fs else (None, 0)

    def prime(self, n=12):
        """Warm start: ingest the last n snapshots in time order so events have history now."""
        self.load_stops()
        for ts, path in self._files_by_ts()[-n:]:
            try:
                self._ingest(self._load(path), ts)
                self.last_file_ts = ts
            except (OSError, ValueError):
                continue
        now = time.time()
        self._evict(now)
        preds = self._rebuild_predictions(now)
        self.snapshot = {'generated': int(now), 'count': len(preds), 'predictions': preds}

    def _load(self, path):
        opener = gzip.open if path.endswith('.gz') else open
        with opener(path, 'rb') as fh:
            return json.loads(fh.read())

    def _ingest(self, data, snap_ts):
        for stop_id, sd in data.items():
            if not isinstance(sd, dict):
                continue
            for dep in sd.get('departures', []) or []:
                if dep.get('status') != 'REALTIME':
                    continue
                route = str(dep.get('routeShortName', '')).strip()
                if route not in GDANSK_ROUTES:
                    continue
                delay = normalize_delay(dep.get('delayInSeconds'))
                if delay is None or delay < -1200 or delay > 3600:
                    continue
                trip, theo = dep.get('trip'), dep.get('theoreticalTime')
                if trip is None or not theo:
                    continue
                theo_ts = parse_iso(theo)
                if theo_ts is None or theo_ts - snap_ts < 0 or theo_ts - snap_ts > 3600:
                    continue
                key = (str(trip), str(stop_id), str(theo))
                ev = self.events.get(key)
                if ev is None:
                    ev = {'meta': (route, str(stop_id), str(dep.get('vehicleService', '')),
                                   str(dep.get('headsign', '')), theo_ts), 'hist': []}
                    self.events[key] = ev
                ev['hist'].append(delay)
                if len(ev['hist']) > 40:
                    ev['hist'] = ev['hist'][-40:]

    def _rebuild_predictions(self, now):
        preds = []
        for key, ev in self.events.items():
            route, stop_id, vsvc, headsign, theo_ts = ev['meta']
            if theo_ts <= now:           # already departed -> not upcoming
                continue
            hist = ev['hist']
            if len(hist) < 2:            # need history for the live model
                continue
            x = self.pred.features(route, stop_id, vsvc, headsign, hist, theo_ts, now)
            model_final = float(self.pred.booster.predict(x)[0])
            ztm = hist[-1]
            gated = abs(ztm) > GATE_DELAY_S   # model unreliable for extreme delays -> trust ZTM
            if gated:
                model_final = ztm
            preds.append({
                'route': route, 'headsign': headsign, 'stop_id': stop_id,
                'stop_name': self.stop_names.get(str(stop_id), str(stop_id)),
                'lead_time_min': round((theo_ts - now) / 60.0, 1),
                'ztm_delay_s': round(ztm),
                'model_final_s': round(model_final),
                'divergence_s': round(model_final - ztm),
                'gated': gated,
            })
        preds.sort(key=lambda p: p['lead_time_min'])   # soonest-departing first
        return preds

    def _evict(self, now):
        for k in [k for k, ev in self.events.items() if ev['meta'][4] < now - 300]:
            del self.events[k]

    def update_once(self):
        path, ts = self._newest_file()
        if not path or ts <= self.last_file_ts:
            return  # no fresh snapshot
        try:
            data = self._load(path)
        except (OSError, ValueError):
            return
        now = time.time()
        with self.lock:
            self._ingest(data, ts)
            self._evict(now)
            preds = self._rebuild_predictions(now)
            self.snapshot = {'generated': int(now), 'count': len(preds), 'predictions': preds}
            self.last_file_ts = ts

    def run_loop(self):
        while True:
            try:
                self.load_stops()   # refreshes once per day
                self.update_once()
            except Exception as e:  # keep the loop alive
                print(f'[updater] error: {e}', flush=True)
            time.sleep(self.poll_s)

    def get(self):
        with self.lock:
            return self.snapshot


def make_handler(store):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj, cache_s=0):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            # Edge/browser caching: snapshot refreshes every ~60s, so a 60s TTL means
            # Cloudflare serves nearly all traffic and the origin (.129) sees ~1 hit/min.
            self.send_header('Cache-Control', f'public, max-age={cache_s}' if cache_s else 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith('/healthz'):
                snap = store.get()
                self._send(200, {'ok': True, 'events': len(store.events),
                                 'count': snap['count'], 'last_snapshot': store.last_file_ts}, cache_s=10)
            elif self.path.startswith('/predictions'):
                self._send(200, store.get(), cache_s=60)
            else:
                self._send(404, {'error': 'not found'})

        def log_message(self, *a):
            pass
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', default='data/results/gdansk_clean/tree_delay_models_dir')
    ap.add_argument('--estimations', default='data/estimations')
    ap.add_argument('--port', type=int, default=8091)
    ap.add_argument('--poll', type=int, default=60)
    args = ap.parse_args()

    predictor = Predictor(args.models, 'fullhist')
    store = Store(args.estimations, predictor, poll_s=args.poll)
    print('Warm-starting from recent snapshots...', flush=True)
    store.prime(12)
    print(f'  events={len(store.events)} predictions={store.get()["count"]}', flush=True)

    threading.Thread(target=store.run_loop, daemon=True).start()
    httpd = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(store))
    print(f'Serving on 127.0.0.1:{args.port} (/healthz /predictions)', flush=True)
    httpd.serve_forever()


if __name__ == '__main__':
    main()
