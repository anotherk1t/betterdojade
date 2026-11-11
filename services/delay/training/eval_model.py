#!/usr/bin/env python3
"""Evaluate a trained (or the existing) model on a dumped validation window."""
import argparse
import json
import math
import os
import time

import numpy as np
import lightgbm as lgb

from common import IDX, fmt_ts
from features import build_X, load_priors, lead_bucket_of_arr

BUCKETS = (('0_5min', 0, 5), ('5_15min', 5, 15), ('15_30min', 15, 30), ('30_60min', 30, 60.0001))
EXISTING_MAP = {
    'route_enc': 'old_route', 'stop_id_enc': 'old_stop',
    'vehicle_service_enc': 'old_vsvc', 'headsign_enc': 'old_headsign',
    'lead_time_min': 'lead_min', 'prev1_delay': 'prev1', 'prev2_delay': 'prev2',
    'obs_total': 'obs_total',
}


def build_X_existing(arr, feats):
    X = np.empty((arr.shape[0], len(feats)), dtype=np.float32)
    for j, f in enumerate(feats):
        X[:, j] = arr[:, IDX[EXISTING_MAP.get(f, f)]]
    return X


class Acc:
    """Streaming metric accumulator for several prediction variants."""

    def __init__(self, n_routes, n_events, variants):
        self.n = 0
        keys = list(variants) + ['ztm']
        self.sae = {k: 0.0 for k in keys}
        self.sse = {k: 0.0 for k in keys}
        self.bias = {k: 0.0 for k in keys}
        self.bucket_n = np.zeros(4, dtype=np.int64)
        self.bucket_sae = {k: np.zeros(4) for k in keys}
        self.bucket_sse = {k: np.zeros(4) for k in keys}
        self.route_n = np.zeros(n_routes, dtype=np.int64)
        self.route_sae = {k: np.zeros(n_routes) for k in keys}
        self.route_sse = {k: np.zeros(n_routes) for k in keys}
        self.ev_n = np.zeros(n_events, dtype=np.int64)
        self.ev_sae = {k: np.zeros(n_events) for k in keys}

    def add(self, y, lead, route, event_id, preds, ztm):
        self.n += len(y)
        # bucket computed from lead directly
        bidx = np.where(lead < 5, 0, np.where(lead < 15, 1, np.where(lead < 30, 2, 3)))
        self.bucket_n += np.bincount(bidx, minlength=4)
        self.route_n += np.bincount(route, minlength=len(self.route_n))
        self.ev_n += np.bincount(event_id, minlength=len(self.ev_n))
        for k, p in preds.items():
            e = np.abs(y - p)
            self.sae[k] += float(e.sum())
            self.sse[k] += float((e * e).sum())
            self.bias[k] += float((p - y).sum())
            self.bucket_sae[k] += np.bincount(bidx, weights=e, minlength=4)
            self.bucket_sse[k] += np.bincount(bidx, weights=e * e, minlength=4)
            self.route_sae[k] += np.bincount(route, weights=e, minlength=len(self.route_n))
            self.route_sse[k] += np.bincount(route, weights=e * e, minlength=len(self.route_n))
            self.ev_sae[k] += np.bincount(event_id, weights=e, minlength=len(self.ev_n))
        e = np.abs(y - ztm)
        self.sae['ztm'] += float(e.sum())
        self.sse['ztm'] += float((e * e).sum())
        self.bias['ztm'] += float((ztm - y).sum())
        self.bucket_sae['ztm'] += np.bincount(bidx, weights=e, minlength=4)
        self.bucket_sse['ztm'] += np.bincount(bidx, weights=e * e, minlength=4)
        self.route_sae['ztm'] += np.bincount(route, weights=e, minlength=len(self.route_n))
        self.route_sse['ztm'] += np.bincount(route, weights=e * e, minlength=len(self.route_n))
        self.ev_sae['ztm'] += np.bincount(event_id, weights=e, minlength=len(self.ev_n))

    def summary(self, variants):
        out = {'rows': int(self.n)}
        for k in variants + ['ztm']:
            out[k] = {
                'mae_s': round(self.sae[k] / self.n, 4),
                'rmse_s': round(math.sqrt(self.sse[k] / self.n), 4),
                'bias_s': round(self.bias[k] / self.n, 4),
            }
        out['gain_vs_ztm_s'] = {k: round((self.sae['ztm'] - self.sae[k]) / self.n, 4) for k in variants}
        out['buckets'] = {}
        for bi, (name, _, _) in enumerate(BUCKETS):
            c = int(self.bucket_n[bi])
            if not c:
                out['buckets'][name] = {'rows': 0}
                continue
            b = {'rows': c}
            for k in variants + ['ztm']:
                b[k] = {
                    'mae_s': round(self.bucket_sae[k][bi] / c, 4),
                    'rmse_s': round(math.sqrt(self.bucket_sse[k][bi] / c), 4),
                }
            b['gain_vs_ztm_s'] = {k: round((self.bucket_sae['ztm'][bi] - self.bucket_sae[k][bi]) / c, 4)
                                  for k in variants}
            out['buckets'][name] = b
        ev = self.ev_n > 0
        out['event_level'] = {
            'events': int(ev.sum()),
            'mae_s': {k: round(float(np.mean(self.ev_sae[k][ev] / self.ev_n[ev])), 4)
                      for k in variants + ['ztm']},
        }
        return out

    def route_table(self, route_names, variant):
        rows = []
        for c in range(len(self.route_n)):
            n = int(self.route_n[c])
            if n == 0:
                continue
            rows.append({
                'route': route_names.get(c, str(c)),
                'route_code': c, 'rows': n,
                'mae_s': round(float(self.route_sae[variant][c] / n), 4),
                'mae_ztm_s': round(float(self.route_sae['ztm'][c] / n), 4),
                'gain_s': round(float((self.route_sae['ztm'][c] - self.route_sae[variant][c]) / n), 4),
                'rmse_s': round(float(math.sqrt(self.route_sse[variant][c] / n)), 4),
                'rmse_ztm_s': round(float(math.sqrt(self.route_sse['ztm'][c] / n)), 4),
            })
        rows.sort(key=lambda r: -r['rows'])
        return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dump', required=True)
    ap.add_argument('--model', required=True, help="'existing' or path to model txt")
    ap.add_argument('--config-json', default='')
    ap.add_argument('--priors', default='')
    ap.add_argument('--vocab', required=True)
    ap.add_argument('--old-models-dir', default='/home/yan/bikerouter/data/results/gdansk_clean/tree_delay_models_dir')
    ap.add_argument('--gate-routes-json', default='')
    ap.add_argument('--gate-lead', type=float, default=5.0)
    ap.add_argument('--gate-delay', type=float, default=1200.0)
    ap.add_argument('--chunk', type=int, default=2000000)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    t0 = time.time()
    meta = json.load(open(args.dump + '.json'))
    ncols = meta['ncols']
    n_rows = meta['n_rows']
    arr = np.memmap(args.dump, dtype=np.float32, mode='r', shape=(n_rows, ncols))
    vocab = json.load(open(args.vocab))
    route_names = {v: k for k, v in vocab['encoders']['route'].items()}
    unk = vocab['unk_index']

    if args.model == 'existing':
        ometa = json.load(open(os.path.join(args.old_models_dir, 'tree_delay_encoders.json')))
        feats = ometa['feature_cols']['fullhist']
        booster = lgb.Booster(model_file=os.path.join(args.old_models_dir, 'delay_fullhist_model.txt'))
        cfg = {'features': feats, 'existing': True}
        priors = None
        build = lambda a: build_X_existing(a, feats)
    else:
        cfg = json.load(open(args.config_json))
        feats = cfg['features']
        booster = lgb.Booster(model_file=args.model)
        priors = load_priors(args.priors) if args.priors else None
        build = lambda a: build_X(a, feats, priors)

    gate_routes = set()
    if args.gate_routes_json:
        g = json.load(open(args.gate_routes_json))
        gate_routes = set(g.get('routes', []))
    gate_codes = {vocab['encoders']['route'].get(r, unk['route']) for r in gate_routes}

    variants = ['raw', 'lead5', 'route', 'delay', 'route_delay', 'lead5_route', 'all']
    acc = Acc(len(route_names) + 1, int(meta['n_events_kept']) + 2, variants)
    unk_cnt = {c: 0 for c in ('route', 'stop', 'vsvc', 'headsign')}
    unk_cols = {'route': ('route', 'route'), 'stop': ('stop', 'stop_id'),
                'vsvc': ('vsvc', 'vehicle_service'), 'headsign': ('headsign', 'headsign')}

    for start in range(0, n_rows, args.chunk):
        end = min(start + args.chunk, n_rows)
        a = arr[start:end]
        X = build(a)
        p = booster.predict(X)
        y = a[:, IDX['target']]
        ztm = a[:, IDX['current_delay']]
        lead = a[:, IDX['lead_min']]
        route = a[:, IDX['route']].astype(np.int64)
        ev = a[:, IDX['event_id']].astype(np.int64)
        m_lead = lead < args.gate_lead
        m_route = np.isin(route, list(gate_codes)) if gate_codes else np.zeros(len(route), dtype=bool)
        m_delay = np.abs(ztm) > args.gate_delay
        preds = {
            'raw': p,
            'lead5': np.where(m_lead, ztm, p),
            'route': np.where(m_route, ztm, p),
            'delay': np.where(m_delay, ztm, p),
            'route_delay': np.where(m_route | m_delay, ztm, p),
            'lead5_route': np.where(m_lead | m_route, ztm, p),
            'all': np.where(m_lead | m_route | m_delay, ztm, p),
        }
        acc.add(y, lead, route, ev, preds, ztm)
        for c, (col, ukey) in unk_cols.items():
            unk_cnt[c] += int((a[:, IDX[col]] == unk[ukey]).sum())
        print(f'  {end:,}/{n_rows:,} rows | elapsed {time.time()-t0:.0f}s', flush=True)

    route_tbl = acc.route_table(route_names, 'raw')
    out = {
        'model': args.model,
        'config': cfg,
        'window': meta['window'],
        'rows': n_rows,
        'events': int(meta['n_events_kept']),
        'unknown_pct': {c: round(100.0 * v / n_rows, 3) for c, v in unk_cnt.items()},
        'metrics': acc.summary(variants),
        'route_table': route_tbl,
        'gate': {'lead_s': args.gate_lead, 'delay_s': args.gate_delay, 'routes': sorted(gate_routes)},
        'elapsed_s': round(time.time() - t0, 1),
    }
    wins = [r for r in route_tbl if r['rows'] >= 50 and r['gain_s'] > 0]
    losses = [r for r in route_tbl if r['rows'] >= 50 and r['gain_s'] <= 0]
    out['route_summary'] = {
        'routes_min50': len(wins) + len(losses),
        'wins_min50': len(wins),
        'losses_min50': len(losses),
        'loss_routes': sorted(losses, key=lambda r: r['gain_s']),
        'worst_gain_routes': sorted(route_tbl, key=lambda r: r['gain_s'])[:12],
        'best_gain_routes': sorted(route_tbl, key=lambda r: -r['gain_s'])[:12],
    }
    with open(args.out, 'w') as f:
        json.dump(out, f, indent=2)
    with open(args.out.replace('.json', '-routes.csv'), 'w') as f:
        f.write('route,rows,mae_s,mae_ztm_s,gain_s,rmse_s,rmse_ztm_s\n')
        for r in route_tbl:
            f.write(','.join(str(r[k]) for k in ('route', 'rows', 'mae_s', 'mae_ztm_s', 'gain_s', 'rmse_s', 'rmse_ztm_s')) + '\n')
    print(json.dumps(out['metrics']['raw'], indent=2), flush=True)
    print('route wins/losses', out['route_summary']['wins_min50'], out['route_summary']['losses_min50'], flush=True)
    print('gates:', {k: out['metrics']['gain_vs_ztm_s'][k] for k in variants}, flush=True)
    print('DONE', round(time.time() - t0, 1), 's', flush=True)


if __name__ == '__main__':
    main()
