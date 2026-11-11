# Delay model training pipeline

Scripts that produced the 38-feature LightGBM artifact in `services/delay/model/`.
The pipeline reads raw departure snapshots from the data host, builds feature rows,
trains, and evaluates on held-out windows.

## Files

| File | Role |
|---|---|
| `common.py` | Snapshot parsing, delay normalisation, dump column layout, shared helpers |
| `features.py` | Feature matrix (`build_X`), prior computation (`compute_priors`), feature configs |
| `dump_rows.py` | Snapshot archive → feature-row dump (`.bin` + `.json` metadata) |
| `scan_vocab.py` | Categorical vocabulary scan for `route`, `stop_id`, `vehicle_service`, `headsign` |
| `make_priors.py` | Prior arrays for a training date range |
| `train_exp.py` | Training entry point and experiment parameter sets |
| `eval_model.py` | Holdout evaluation, lead buckets, route table, optional gating |

Requirements: Python 3, `numpy`, `lightgbm` (4.6 used for the packaged model). Install with
`pip install -r ../requirements.txt`.

## Feature builder

The model consumes **38 features**, in the exact order stored in
`services/delay/model/training_config.json`. Nineteen are base features and nineteen are
derived from training-window priors and the observation history.

Base (19):

```
route, stop, vsvc, headsign,
lead_min, hour, dow, hour_sin, hour_cos, dow_sin, dow_cos,
current_delay, prev1, prev2, delta_prev1, delta_prev2,
hist_mean3, hist_std3, obs_index
```

Derived (19):

```
hist_mean5, hist_std5, obs_span_min, trend_per_min, lead_bucket,
route_mean_target, route_mean_corr, route_mean_current,
stop_mean_target, stop_mean_corr, stop_std_target,
vsvc_mean_corr, route_bucket_corr, global_bucket_corr,
current_minus_route_mean, current_plus_trend, hist_mean3_plus_trend,
route_corr_lead, stop_corr_lead
```

Key definitions:

- `lead_min = clip((theoretical_ts - snapshot_ts) / 60, 0, 60)`.
- `lead_bucket`: `0` for lead < 5 min, `1` for < 15, `2` for < 30, `3` otherwise.
- `obs_span_min = (snapshot_ts - first_snapshot_ts) / 60`.
- `trend_per_min = clip((current_delay - first_delay) / max(obs_span_min, 0.5), -30, 30)`
  when `obs_span_min > 0.5`, otherwise `0`.
- `hist_mean3` / `hist_std3` over the last 3 delays; `hist_mean5` / `hist_std5` over the last 5
  (population standard deviation).
- `obs_index = len(history) - 1`; there is no `obs_total` feature.
- Prior lookups use the encoded categorical code. `route_bucket_corr` indexes
  `[route_code, lead_bucket]`.
- `current_minus_route_mean = current_delay - route_mean_current`.
- `current_plus_trend = current_delay + trend_per_min * lead_min`.
- `hist_mean3_plus_trend = hist_mean3 + trend_per_min * lead_min`.
- `route_corr_lead = route_mean_corr * min(lead_min, 30) / 30`.
- `stop_corr_lead = stop_mean_corr * min(lead_min, 30) / 30`.

Categorical strings are mapped through `services/delay/model/vocab.json["encoders"][column]`,
falling back to `vocab.json["unk_index"][column]`.

### Not a drop-in replacement

This artifact is **not compatible** with the previous 20-feature loader in
`services/delay/delay_service.py`. That loader builds `route_enc`, `stop_id_enc`,
`vehicle_service_enc`, `headsign_enc`, `lead_time_min`, `prev1_delay`, `prev2_delay` and
`obs_total`. The new model expects the names above, requires `(snapshot_ts, delay)` history for
`obs_span_min` and `trend_per_min`, and needs the prior arrays from `priors.npz`. Serving code
must be updated before loading this booster; see `services/delay/model/README.md`.

## End-to-end run

```bash
cd services/delay/training
python3 -m venv .venv
.venv/bin/pip install -r ../requirements.txt

# 1. Vocabulary over pre-holdout days
.venv/bin/python scan_vocab.py \
  --days 2026-09-03,2026-09-10,2026-09-17,2026-09-24,2026-10-01,2026-10-08,2026-10-15,2026-10-20,2026-10-23,2026-10-24,2026-04-22,2026-04-25,2026-04-28 \
  --out vocab.json --workers 6

# 2. Feature rows (event-sampled for training, full for holdouts)
.venv/bin/python dump_rows.py --start 2026-09-01T00:00:00 --end 2026-10-25T00:00:00 \
  --vocab vocab.json --out dumps/train_sepoct.bin --event-rate 0.07 --workers 6
.venv/bin/python dump_rows.py --start 2026-10-25T00:00:00 --end 2026-11-01T00:00:00 \
  --vocab vocab.json --out dumps/val_oct.bin --event-rate 1.0 --workers 6
.venv/bin/python dump_rows.py --start 2026-05-01T00:00:00 --end 2026-05-08T00:00:00 \
  --vocab vocab.json --out dumps/val_may.bin --event-rate 1.0 --workers 6

# 3. Train
.venv/bin/python train_exp.py \
  --dumps dumps/train_sepoct.bin \
  --train-start 2026-09-01 --train-end 2026-10-22 --val-end 2026-10-25 \
  --config rich --params p2_l1_fast \
  --max-train-rows 6000000 --num-boost-round 2500 --early-stopping 80 --threads 10 \
  --priors-out out/priors.npz \
  --out-model out/delay_l1_model.txt --out-json out/training_config.json

# 4. Evaluate
.venv/bin/python eval_model.py --dump dumps/val_oct.bin \
  --model out/delay_l1_model.txt --config-json out/training_config.json \
  --priors out/priors.npz --vocab vocab.json --out out/val_oct.json
```

`--train-start` excludes earlier rows from both the fit and the priors. The saved artifact used
2026-09-01 … 2026-10-21 for fitting, 2026-10-22 … 24 for early stopping, 2026-10-25 … 11-01 and
2026-05-01 … 07 as holdouts.

## Refreshing the serving artifact

1. Re-run `scan_vocab.py`, `dump_rows.py`, `train_exp.py`, and `eval_model.py`.
2. Copy `delay_l1_model.txt`, `priors.npz`, `vocab.json`, and `training_config.json` into
   `services/delay/model/`.
3. Re-derive `gate_routes.json` from the internal calibration window (routes with at least 100
   rows and negative gain). The current gate is `131`, `N16`.
4. Keep the `|ZTM| > 1200 s` passthrough in the service; do not gate lead times below 5 min.
5. Restart the service and verify `/healthz` and `/predictions`.

The booster is about 28 MB. Training the final configuration takes roughly 10 minutes on
10 cores; extraction takes about a minute per day of snapshots.
