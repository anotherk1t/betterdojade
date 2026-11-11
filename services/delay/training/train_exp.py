#!/usr/bin/env python3
"""Train one experiment on the dumped feature rows."""
import argparse
import gc
import json
import os
import time
from datetime import datetime, timezone

import numpy as np
import lightgbm as lgb

from common import IDX, fmt_ts
from features import CONFIGS, build_X, compute_priors, save_priors, load_priors, lead_bucket_of_arr

PARAMS = {
    'p1_base': dict(objective='regression', learning_rate=0.05, num_leaves=64,
                    min_child_samples=60, subsample=0.8, subsample_freq=1,
                    colsample_bytree=0.8, reg_lambda=0.0),
    'p2_leaves128': dict(objective='regression', learning_rate=0.05, num_leaves=128,
                         min_child_samples=100, subsample=0.8, subsample_freq=1,
                         colsample_bytree=0.8, reg_lambda=0.0),
    'p3_leaves255': dict(objective='regression', learning_rate=0.03, num_leaves=255,
                         min_child_samples=200, subsample=0.8, subsample_freq=1,
                         colsample_bytree=0.7, reg_lambda=5.0),
    'p4_leaves128_l2': dict(objective='regression', learning_rate=0.03, num_leaves=128,
                            min_child_samples=200, subsample=0.9, subsample_freq=1,
                            colsample_bytree=0.6, reg_lambda=5.0),
    'p5_leaves512': dict(objective='regression', learning_rate=0.03, num_leaves=512,
                         min_child_samples=300, subsample=0.8, subsample_freq=1,
                         colsample_bytree=0.6, reg_lambda=10.0),
    'p6_small_lr': dict(objective='regression', learning_rate=0.02, num_leaves=96,
                        min_child_samples=300, subsample=0.9, subsample_freq=1,
                        colsample_bytree=0.9, reg_lambda=1.0),
    'p2_l1': dict(objective='regression_l1', learning_rate=0.05, num_leaves=128,
                  min_child_samples=100, subsample=0.8, subsample_freq=1,
                  colsample_bytree=0.8, reg_lambda=0.0),
    'p3_l1': dict(objective='regression_l1', learning_rate=0.03, num_leaves=255,
                  min_child_samples=200, subsample=0.8, subsample_freq=1,
                  colsample_bytree=0.7, reg_lambda=5.0),
    'p2_l1_fast': dict(objective='regression_l1', learning_rate=0.05, num_leaves=128,
                       min_child_samples=100, subsample=0.8, subsample_freq=1,
                       colsample_bytree=0.8, reg_lambda=0.0, max_bin=127,
                       force_col_wise=True),
    'p3_l1_fast': dict(objective='regression_l1', learning_rate=0.03, num_leaves=255,
                       min_child_samples=200, subsample=0.8, subsample_freq=1,
                       colsample_bytree=0.7, reg_lambda=5.0, max_bin=127,
                       force_col_wise=True),
}


def day(iso):
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() // 86400


def load_dumps(paths):
    arrs, metas = [], []
    for p in paths:
        meta = json.load(open(p + '.json'))
        a = np.fromfile(p, dtype=np.float32).reshape(-1, meta['ncols'])
        print(f'  loaded {p}: {a.shape} ({a.nbytes/1e9:.2f} GB)', flush=True)
        arrs.append(a)
        metas.append(meta)
    return (arrs[0] if len(arrs) == 1 else np.concatenate(arrs, axis=0)), metas


def metrics(y, p, ztm, lead, route):
    out = {
        'rows': int(len(y)),
        'mae_s': round(float(np.mean(np.abs(y - p))), 4),
        'rmse_s': round(float(np.sqrt(np.mean((y - p) ** 2))), 4),
        'bias_s': round(float(np.mean(p - y)), 4),
        'mae_ztm_s': round(float(np.mean(np.abs(y - ztm))), 4),
        'rmse_ztm_s': round(float(np.sqrt(np.mean((y - ztm) ** 2))), 4),
        'bias_ztm_s': round(float(np.mean(ztm - y)), 4),
        'buckets': {},
    }
    out['gain_s'] = round(out['mae_ztm_s'] - out['mae_s'], 4)
    for name, lo, hi in (('0_5min', 0, 5), ('5_15min', 5, 15), ('15_30min', 15, 30), ('30_60min', 30, 60.0001)):
        m = (lead >= lo) & (lead < hi)
        c = int(m.sum())
        if not c:
            out['buckets'][name] = {'rows': 0}
            continue
        out['buckets'][name] = {
            'rows': c,
            'mae_s': round(float(np.mean(np.abs(y[m] - p[m]))), 4),
            'rmse_s': round(float(np.sqrt(np.mean((y[m] - p[m]) ** 2))), 4),
            'mae_ztm_s': round(float(np.mean(np.abs(y[m] - ztm[m]))), 4),
            'gain_s': round(float(np.mean(np.abs(y[m] - ztm[m])) - np.mean(np.abs(y[m] - p[m]))), 4),
        }
    out['route_table'] = route_table(y, p, ztm, route)
    wins = [r for r in out['route_table'] if r['rows'] >= 50 and r['gain_s'] > 0]
    losses = [r for r in out['route_table'] if r['rows'] >= 50 and r['gain_s'] <= 0]
    out['route_summary'] = {
        'routes_min50': len(wins) + len(losses),
        'wins_min50': len(wins),
        'losses_min50': len(losses),
        'loss_routes': sorted([r for r in losses], key=lambda r: r['gain_s']),
    }
    return out


def route_table(y, p, ztm, route):
    n = int(route.max()) + 1
    cnt = np.bincount(route, minlength=n)
    ae = np.bincount(route, weights=np.abs(y - p), minlength=n)
    ze = np.bincount(route, weights=np.abs(y - ztm), minlength=n)
    se = np.bincount(route, weights=(y - p) ** 2, minlength=n)
    zse = np.bincount(route, weights=(y - ztm) ** 2, minlength=n)
    rows = []
    for c in range(n):
        if cnt[c] == 0:
            continue
        rows.append({
            'route_code': int(c), 'rows': int(cnt[c]),
            'mae_s': round(float(ae[c] / cnt[c]), 4),
            'mae_ztm_s': round(float(ze[c] / cnt[c]), 4),
            'gain_s': round(float((ze[c] - ae[c]) / cnt[c]), 4),
            'rmse_s': round(float(np.sqrt(se[c] / cnt[c])), 4),
            'rmse_ztm_s': round(float(np.sqrt(zse[c] / cnt[c])), 4),
        })
    rows.sort(key=lambda r: -r['rows'])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dumps', nargs='+', required=True)
    ap.add_argument('--config', default='rich')
    ap.add_argument('--params', default='p1_base')
    ap.add_argument('--train-end', default='2026-10-22', help='internal val starts here (exclusive train)')
    ap.add_argument('--val-end', default='2026-10-25')
    ap.add_argument('--train-start', default='')
    ap.add_argument('--weight-half-life', type=float, default=0.0,
                    help='recency half-life in days relative to val-end; 0 = unweighted')
    ap.add_argument('--max-train-rows', type=int, default=0, help='event-subsample training rows')
    ap.add_argument('--num-boost-round', type=int, default=1500)
    ap.add_argument('--early-stopping', type=int, default=80)
    ap.add_argument('--cat-route', action='store_true')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--threads', type=int, default=6)
    ap.add_argument('--priors-out', default='')
    ap.add_argument('--priors-in', default='')
    ap.add_argument('--out-model', required=True)
    ap.add_argument('--out-json', required=True)
    args = ap.parse_args()

    t0 = time.time()
    print('=' * 70, flush=True)
    print('train_exp', args.config, args.params, flush=True)
    arr, metas = load_dumps(args.dumps)
    print(f'total rows {arr.shape[0]:,}', flush=True)

    theo_day = arr[:, IDX['theo_day']].astype(np.int64)
    d_tr_end = day(args.train_end)
    d_val_end = day(args.val_end)
    d_tr_start = day(args.train_start) if args.train_start else -10**9

    train_mask = (theo_day >= d_tr_start) & (theo_day < d_tr_end)
    val_mask = (theo_day >= d_tr_end) & (theo_day < d_val_end)
    print(f'train rows {train_mask.sum():,} | internal val rows {val_mask.sum():,} | '
          f'window {args.train_start or "all"} .. {args.train_end} / {args.val_end}', flush=True)
    if not train_mask.any() or not val_mask.any():
        raise SystemExit('empty split')

    if args.priors_in:
        priors = load_priors(args.priors_in)
        print('loaded priors', args.priors_in, flush=True)
    else:
        priors = compute_priors(arr, train_mask)
        if args.priors_out:
            save_priors(priors, args.priors_out)
            print('saved priors', args.priors_out, flush=True)

    feats = CONFIGS[args.config]
    atr = arr[train_mask]
    ava = arr[val_mask]
    Xtr = build_X(atr, feats, priors)
    ytr = atr[:, IDX['target']].copy()
    Xva = build_X(ava, feats, priors)
    yva = ava[:, IDX['target']].copy()
    ztm_va = ava[:, IDX['current_delay']].copy()
    lead_va = ava[:, IDX['lead_min']].copy()
    route_va = ava[:, IDX['route']].astype(np.int64).copy()
    theo_day_tr = atr[:, IDX['theo_day']].astype(np.float64).copy()
    ev_tr = atr[:, IDX['event_id']].astype(np.int64).copy()
    del atr, ava
    gc.collect()

    # event-level subsample for the training rows
    keep = None
    if args.max_train_rows and len(ytr) > args.max_train_rows:
        ev = ev_tr
        uniq = np.unique(ev)
        # deterministic pseudo-random event selection
        h = (uniq.astype(np.uint64) * np.uint64(2654435761)) % np.uint64(2 ** 32)
        keep_events = uniq[h < int(0.5 + (args.max_train_rows / len(ytr)) * 2 ** 32)]
        keep = np.isin(ev, keep_events)
        Xtr = Xtr[keep]
        ytr = ytr[keep]
        theo_day_tr = theo_day_tr[keep]
        print(f'event-subsampled train rows to {len(ytr):,} ({len(keep_events):,} events)', flush=True)

    wtr = None
    if args.weight_half_life > 0:
        age = np.maximum(d_val_end - theo_day_tr, 0)
        wtr = np.power(0.5, age / args.weight_half_life).astype(np.float32)
        print(f'weights: min={wtr.min():.3f} mean={wtr.mean():.3f} max={wtr.max():.3f}', flush=True)

    params = dict(PARAMS[args.params])
    params.update({
        'seed': args.seed, 'num_threads': args.threads, 'verbosity': -1,
        'metric': 'mae',
    })
    cat = ['route'] if args.cat_route else 'auto'
    ds_params = {}
    if 'max_bin' in params:
        ds_params['max_bin'] = params.pop('max_bin')
    dtrain = lgb.Dataset(Xtr, label=ytr, weight=wtr, free_raw_data=True,
                         categorical_feature=cat,
                         params=ds_params if ds_params else None)
    dval = lgb.Dataset(Xva, label=yva, reference=dtrain, free_raw_data=False)
    dtrain.construct()
    del Xtr
    gc.collect()

    callbacks = [lgb.early_stopping(args.early_stopping, verbose=True),
                 lgb.log_evaluation(100)]
    model = lgb.train(params, dtrain, num_boost_round=args.num_boost_round,
                      valid_sets=[dval], valid_names=['val'], callbacks=callbacks)

    pva = model.predict(Xva, num_iteration=model.best_iteration)
    m = metrics(yva, pva, ztm_va, lead_va, route_va)

    imp = sorted(zip(feats, model.feature_importance('gain')), key=lambda x: -x[1])
    try:
        best_score = float(model.best_score['val']['l1'])
    except KeyError:
        best_score = float(list(model.best_score['val'].values())[0])
    out = {
        'config': args.config,
        'params_name': args.params,
        'params': params,
        'features': feats,
        'n_features': len(feats),
        'cat_route': args.cat_route,
        'train': {
            'dumps': args.dumps,
            'train_start': args.train_start or None,
            'train_end_exclusive': args.train_end,
            'val_end_exclusive': args.val_end,
            'rows': int(len(ytr)),
            'weight_half_life_days': args.weight_half_life or None,
            'max_train_rows': args.max_train_rows or None,
        },
        'best_iteration': int(model.best_iteration or args.num_boost_round),
        'best_score_mae': best_score,
        'internal_val': m,
        'feature_importance_gain': [{'feature': f, 'gain': float(g)} for f, g in imp],
        'elapsed_s': round(time.time() - t0, 1),
    }
    os.makedirs(os.path.dirname(args.out_model) or '.', exist_ok=True)
    model.save_model(args.out_model, num_iteration=model.best_iteration)
    with open(args.out_json, 'w') as f:
        json.dump(out, f, indent=2)
    print(json.dumps({k: out[k] for k in ('config', 'params_name', 'best_iteration', 'best_score_mae', 'elapsed_s')}, indent=2), flush=True)
    print('internal val:', m['mae_s'], 'vs ztm', m['mae_ztm_s'], 'gain', m['gain_s'], flush=True)
    print('top feats:', imp[:12], flush=True)
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
