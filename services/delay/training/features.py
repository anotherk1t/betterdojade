#!/usr/bin/env python3
"""Feature matrix construction shared by training and evaluation."""
import numpy as np

from common import IDX, NCOLS

# 19 features that do not depend on knowing the final observation count.
BASE_FEATS = [
    'route', 'stop', 'vsvc', 'headsign',
    'lead_min', 'hour', 'dow', 'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos',
    'current_delay', 'prev1', 'prev2', 'delta_prev1', 'delta_prev2',
    'hist_mean3', 'hist_std3', 'obs_index',
]
RICH_EXTRA = [
    'hist_mean5', 'hist_std5', 'obs_span_min', 'trend_per_min',
    'lead_bucket',
    'route_mean_target', 'route_mean_corr', 'route_mean_current',
    'stop_mean_target', 'stop_mean_corr', 'stop_std_target',
    'vsvc_mean_corr', 'route_bucket_corr', 'global_bucket_corr',
    'current_minus_route_mean', 'current_plus_trend', 'hist_mean3_plus_trend',
    'route_corr_lead', 'stop_corr_lead',
]

CONFIGS = {
    'base19': BASE_FEATS,
    'base20_off': BASE_FEATS + ['obs_total'],
    'base20_on': BASE_FEATS + ['obs_count'],
    'rich': BASE_FEATS + RICH_EXTRA,
    'rich_on': BASE_FEATS + RICH_EXTRA + ['obs_count'],
    'rich_off': BASE_FEATS + RICH_EXTRA + ['obs_total'],
}


def lead_bucket(lead):
    return np.where(lead < 5.0, 0, np.where(lead < 15.0, 1,
                    np.where(lead < 30.0, 2, 3))).astype(np.int64)


def _smooth(cnt, s, prior, m):
    return (s + m * prior) / (cnt + m)


def compute_priors(arr, mask=None, n_route=256, n_stop=4096, n_vsvc=4096):
    """Aggregate leakage-free priors from training rows only."""
    if mask is None:
        mask = np.ones(arr.shape[0], dtype=bool)
    a = arr[mask]
    route = a[:, IDX['route']].astype(np.int64)
    stop = a[:, IDX['stop']].astype(np.int64)
    vsvc = a[:, IDX['vsvc']].astype(np.int64)
    lead = a[:, IDX['lead_min']]
    cur = a[:, IDX['current_delay']].astype(np.float64)
    tgt = a[:, IDX['target']].astype(np.float64)
    corr = tgt - cur
    bucket = lead_bucket(lead)

    n_route = max(n_route, int(route.max()) + 2)
    n_stop = max(n_stop, int(stop.max()) + 2)
    n_vsvc = max(n_vsvc, int(vsvc.max()) + 2)

    g_t = float(tgt.mean())
    g_c = float(corr.mean())
    g_cur = float(cur.mean())
    g_var = float(tgt.var())

    def agg(idx, values, size, m, prior):
        cnt = np.bincount(idx, minlength=size).astype(np.float64)
        s = np.bincount(idx, weights=values, minlength=size)
        return _smooth(cnt, s, prior, m), cnt

    route_t, route_cnt = agg(route, tgt, n_route, 2000, g_t)
    route_c, _ = agg(route, corr, n_route, 2000, g_c)
    route_cur, _ = agg(route, cur, n_route, 2000, g_cur)
    stop_t, stop_cnt = agg(stop, tgt, n_stop, 200, g_t)
    stop_c, _ = agg(stop, corr, n_stop, 200, g_c)
    vsvc_c, _ = agg(vsvc, corr, n_vsvc, 100, g_c)

    stop_sq = np.bincount(stop, weights=tgt * tgt, minlength=n_stop)
    stop_var = np.maximum(stop_sq / np.maximum(stop_cnt, 1) - stop_t * stop_t, 0.0)
    stop_std = _smooth(stop_cnt, np.sqrt(stop_var) * stop_cnt, np.sqrt(g_var), 200)

    # route x lead-bucket correction, smoothed towards the route correction
    rb = route * 4 + bucket
    rb_cnt = np.bincount(rb, minlength=n_route * 4).astype(np.float64).reshape(n_route, 4)
    rb_sum = np.bincount(rb, weights=corr, minlength=n_route * 4).reshape(n_route, 4)
    rb_corr = (rb_sum + 300.0 * route_c[:, None]) / (rb_cnt + 300.0)

    gb_cnt = np.bincount(bucket, minlength=4).astype(np.float64)
    gb_sum = np.bincount(bucket, weights=corr, minlength=4)
    gb_corr = gb_sum / np.maximum(gb_cnt, 1)

    return {
        'route_mean_target': route_t, 'route_mean_corr': route_c,
        'route_mean_current': route_cur, 'route_cnt': route_cnt,
        'stop_mean_target': stop_t, 'stop_mean_corr': stop_c,
        'stop_std_target': stop_std, 'stop_cnt': stop_cnt,
        'vsvc_mean_corr': vsvc_c,
        'route_bucket_corr': rb_corr, 'global_bucket_corr': gb_corr,
        'global_mean_target': g_t, 'global_mean_corr': g_c,
        'global_mean_current': g_cur,
    }


def save_priors(priors, path):
    np.savez_compressed(path, **{k: np.asarray(v) for k, v in priors.items()})


def load_priors(path):
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def build_X(arr, feats, priors=None):
    """Build a float32 feature matrix for the requested feature names."""
    n = arr.shape[0]
    X = np.empty((n, len(feats)), dtype=np.float32)
    lead = np.clip(arr[:, IDX['lead_min']], 0.0, 60.0)
    cur = arr[:, IDX['current_delay']]
    bucket = lead_bucket(lead)
    trend = np.clip(arr[:, IDX['trend_per_min']], -30.0, 30.0)

    route = arr[:, IDX['route']].astype(np.int64)
    stop = arr[:, IDX['stop']].astype(np.int64)
    vsvc = arr[:, IDX['vsvc']].astype(np.int64)
    if priors is not None:
        route = np.minimum(route, len(priors['route_mean_target']) - 1)
        stop = np.minimum(stop, len(priors['stop_mean_target']) - 1)
        vsvc = np.minimum(vsvc, len(priors['vsvc_mean_corr']) - 1)

    for j, f in enumerate(feats):
        if f == 'lead_min':
            X[:, j] = lead
        elif f == 'lead_bucket':
            X[:, j] = bucket
        elif f == 'trend_per_min':
            X[:, j] = trend
        elif f == 'route_mean_target':
            X[:, j] = priors['route_mean_target'][route]
        elif f == 'route_mean_corr':
            X[:, j] = priors['route_mean_corr'][route]
        elif f == 'route_mean_current':
            X[:, j] = priors['route_mean_current'][route]
        elif f == 'stop_mean_target':
            X[:, j] = priors['stop_mean_target'][stop]
        elif f == 'stop_mean_corr':
            X[:, j] = priors['stop_mean_corr'][stop]
        elif f == 'stop_std_target':
            X[:, j] = priors['stop_std_target'][stop]
        elif f == 'vsvc_mean_corr':
            X[:, j] = priors['vsvc_mean_corr'][vsvc]
        elif f == 'route_bucket_corr':
            X[:, j] = priors['route_bucket_corr'][route, bucket]
        elif f == 'global_bucket_corr':
            X[:, j] = priors['global_bucket_corr'][bucket]
        elif f == 'current_minus_route_mean':
            X[:, j] = cur - priors['route_mean_current'][route]
        elif f == 'current_plus_trend':
            X[:, j] = cur + trend * lead
        elif f == 'hist_mean3_plus_trend':
            X[:, j] = arr[:, IDX['hist_mean3']] + trend * lead
        elif f == 'route_corr_lead':
            X[:, j] = priors['route_mean_corr'][route] * np.minimum(lead, 30.0) / 30.0
        elif f == 'stop_corr_lead':
            X[:, j] = priors['stop_mean_corr'][stop] * np.minimum(lead, 30.0) / 30.0
        else:
            X[:, j] = arr[:, IDX[f]]
    return X


def lead_bucket_of_arr(arr):
    return lead_bucket(arr[:, IDX['lead_min']])
