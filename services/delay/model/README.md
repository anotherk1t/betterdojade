# Best delay model — serving artifact

Files:

| File | Contents |
|---|---|
| `delay_l1_model.txt` | LightGBM booster, 2,500 trees, 128 leaves, L1 objective |
| `priors.npz` | Training-window aggregate priors (route / stop / vehicle-service / route×lead-bucket) |
| `vocab.json` | Categorical vocabularies (`route`, `stop_id`, `vehicle_service`, `headsign`) + `unk_index` |
| `training_config.json` | Exact feature list, params, train window, metrics, feature importance |
| `gate_routes.json` | Route gate derived from the internal calibration window (`131`, `N16`) |

## Feature recipe (38 features, order in `training_config.json`)

19 base features (no `obs_total`):

```
route, stop, vsvc, headsign,
lead_min, hour, dow, hour_sin, hour_cos, dow_sin, dow_cos,
current_delay, prev1, prev2, delta_prev1, delta_prev2,
hist_mean3, hist_std3, obs_index
```

19 derived features:

```
hist_mean5, hist_std5, obs_span_min, trend_per_min, lead_bucket,
route_mean_target, route_mean_corr, route_mean_current,
stop_mean_target, stop_mean_corr, stop_std_target,
vsvc_mean_corr, route_bucket_corr, global_bucket_corr,
current_minus_route_mean, current_plus_trend, hist_mean3_plus_trend,
route_corr_lead, stop_corr_lead
```

Definitions (match `features.py::build_X`):

- `lead_min = clip((theo_ts - now)/60, 0, 60)`
- `lead_bucket = 0 if lead<5, 1 if <15, 2 if <30, else 3`
- `trend_per_min = clip((current_delay - first_delay) / max(obs_span_min, 0.5), -30, 30)`
  when `obs_span_min > 0.5`, else `0`
- `obs_span_min = (now - first_snapshot_ts)/60`
- `hist_mean3/std3` over the last 3 delays; `hist_mean5/std5` over the last 5
  (population std)
- `obs_index = len(hist) - 1`
- `route_mean_target = priors.route_mean_target[route_code]`
- `route_mean_corr = priors.route_mean_corr[route_code]`
- `route_mean_current = priors.route_mean_current[route_code]`
- `stop_mean_target = priors.stop_mean_target[stop_code]`
- `stop_mean_corr = priors.stop_mean_corr[stop_code]`
- `stop_std_target = priors.stop_std_target[stop_code]`
- `vsvc_mean_corr = priors.vsvc_mean_corr[vsvc_code]`
- `route_bucket_corr = priors.route_bucket_corr[route_code, lead_bucket]`
- `global_bucket_corr = priors.global_bucket_corr[lead_bucket]`
- `current_minus_route_mean = current_delay - route_mean_current`
- `current_plus_trend = current_delay + trend_per_min * lead_min`
- `hist_mean3_plus_trend = hist_mean3 + trend_per_min * lead_min`
- `route_corr_lead = route_mean_corr * min(lead_min, 30)/30`
- `stop_corr_lead = stop_mean_corr * min(lead_min, 30)/30`

Categorical codes: look up the raw string in `vocab.json["encoders"][col]`;
fall back to `vocab.json["unk_index"][col]`.

## Service changes required

The current `delay_service.py` keeps only a list of delays per event. The new
model needs two extra history values:

1. Store `(snapshot_ts, delay)` per observation, not just `delay`.
2. Compute `obs_span_min` and `trend_per_min` from that history.
3. Look up the prior arrays by the encoded route/stop/vehicle-service code.
4. Do **not** pass `obs_total`; the model has no such feature.
5. Keep the `abs(ztm) > 1200 s` safety passthrough (it improves overall MAE by
   0.68 s on October and 0.41 s on May).
6. Gate routes `131` and `N16` to ZTM (derived from the internal calibration
   window; costs nothing in overall MAE and removes the only October loss).
7. Do **not** gate lead times below 5 min: the new model wins that segment by
   +4.80 s MAE on October.

## Reference metrics

| Window | MAE | RMSE | ZTM MAE | Gain vs ZTM | Route wins |
|---|---:|---:|---:|---:|---:|
| 2026-10-25 … 2026-11-01, raw | 57.16 s | 110.75 s | 90.03 s | +32.87 s (36.5 %) | 88/89 |
| **2026-10-25 … 2026-11-01, route + delay gate** | **56.47 s** | **110.66 s** | **90.03 s** | **+33.56 s (37.3 %)** | 88/89 |
| 2026-05-01 … 2026-05-07, raw | 62.53 s | 111.37 s | 119.15 s | +56.62 s (47.5 %) | 90/92 |
| 2026-05-01 … 2026-05-07, route + delay gate | 62.13 s | 111.42 s | 119.15 s | +57.02 s (47.9 %) | 90/92 |

Training: 6.0 M event-sampled rows (362 k events) from 8.26 M rows,
fit 2026-09-01 … 2026-10-21; 2026-10-22 … 24 used only for early stopping.
