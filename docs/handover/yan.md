# Yan — Delay backend handover

**Branch:** `yan/delay-backend`
**Goal:** hosted LightGBM prediction API that is honestly better than ZTM, with the
`obs_total` skew removed.

## Context

- Validation: `docs/spikes/lightgbm-validation.md`
- Improvement report: `docs/spikes/predictor-improvement.md`
- Summary metrics: `docs/spikes/predictor-improvement-summary.json`
- Current service: `services/delay/delay_service.py`
- Predictor on the homeserver: `127.0.0.1:8091` (`/healthz`, `/predictions`)
- Model artifact: `services/delay/model/` (booster, priors, vocab, training config, gate routes)
- Training pipeline: `services/delay/training/`
- Data: `/home/yan/bikerouter/data/{estimations,delays,alerts,results}`

## Improved model results

The new artifact is a 38-feature LightGBM with an L1 objective, route/stop/vehicle-service
priors and observation-span/trend features. It has no `obs_total` feature, so the previous
online approximation is gone.

| Window | Raw MAE | Gated MAE | ZTM MAE | Gain (gated) |
|---|---:|---:|---:|---:|
| 2026-10-25 … 2026-11-01 | 57.16 s | **56.47 s** | 90.03 s | +33.56 s (37.3 %) |
| 2026-05-01 … 2026-05-07 | 62.53 s | **62.13 s** | 119.15 s | +57.02 s (47.9 %) |

- **88 of 89 October routes win** against ZTM; the only loss is route 131.
- The 0–5 min lead bucket now **wins by 4.80 s** (28.03 s vs ZTM 32.82 s).
- May is statistically unchanged versus the previous model (62.53 s vs 62.57 s raw), so the
  October gain does not cost out-of-time accuracy.
- The booster is about **28 MB** (`services/delay/model/delay_l1_model.txt`).

## Integration: 38-feature builder

The new model is **not a drop-in replacement** for the old 20-feature loader in
`delay_service.py`. The old loader builds `route_enc`, `stop_id_enc`, `vehicle_service_enc`,
`headsign_enc`, `lead_time_min`, `prev1_delay`, `prev2_delay` and `obs_total`; the booster
expects the 38 names and order in `services/delay/model/training_config.json`.

1. Change the event history to store `(snapshot_ts, delay)` per observation, not only delays.
2. Encode `route`, `stop_id`, `vehicle_service` and `headsign` with
   `services/delay/model/vocab.json["encoders"]`; fall back to `vocab.json["unk_index"]`.
3. Build the 19 base features: `route`, `stop`, `vsvc`, `headsign`, `lead_min`, `hour`, `dow`,
   `hour_sin`, `hour_cos`, `dow_sin`, `dow_cos`, `current_delay`, `prev1`, `prev2`,
   `delta_prev1`, `delta_prev2`, `hist_mean3`, `hist_std3`, `obs_index`.
4. Build the 19 derived features: `hist_mean5`, `hist_std5`, `obs_span_min`, `trend_per_min`,
   `lead_bucket`, `route_mean_target`, `route_mean_corr`, `route_mean_current`,
   `stop_mean_target`, `stop_mean_corr`, `stop_std_target`, `vsvc_mean_corr`,
   `route_bucket_corr`, `global_bucket_corr`, `current_minus_route_mean`,
   `current_plus_trend`, `hist_mean3_plus_trend`, `route_corr_lead`, `stop_corr_lead`.
5. Load `services/delay/model/priors.npz` and index the prior arrays by encoded code;
   `route_bucket_corr` uses `[route_code, lead_bucket]`.
6. Do **not** pass `obs_total`. Use `obs_index = len(history) - 1`.
7. Keep the feature order exactly as in `training_config.json`; LightGBM matches by position
   when predicting from a matrix.
8. Verify parity by replaying a snapshot window and comparing the service output with
   `services/delay/training/eval_model.py` on the same rows. A mismatch almost always means a
   feature-order, encoding, or `trend_per_min` history problem.

`obs_span_min` and `trend_per_min` are the only features that need timestamps. If the service
cannot store them yet, set both to zero as a temporary fallback; the prior features still work,
but part of the gain is lost.

## Gating

- Routes `131` and `N16` → ZTM.
- `|ZTM delay| > 1200 s` → ZTM passthrough.
- Do **not** gate lead times below 5 min; the new model wins that segment by 4.80 s.

The route gate comes from the internal calibration window (routes with at least 100 rows and
negative gain) and removes the only October loss. The delay gate improves MAE by 0.68 s on
October and 0.41 s on May.

## Deployment and monitoring tasks

1. Integrate the 38-feature builder into `delay_service.py`.
2. Expose `/healthz` and `/predictions` with CORS and a 60 s cache.
3. Deploy to the personal website / Cloudflare Tunnel.
4. Update the delays dashboard to show model vs ZTM and the gated flag.
5. Add monitoring for feed age (`last_snapshot`), prediction count, load errors, and the share
   of gated predictions.
6. When ground truth arrives, compute daily MAE for model and ZTM; alert if the model falls
   behind ZTM for a full day or if the feed is stale for more than 5 minutes.
7. Refresh the model monthly: rerun the training pipeline, copy the new booster/priors/vocab/
   config into `services/delay/model/`, re-derive `gate_routes.json`, restart, and re-check
   `/healthz` and `/predictions`.
8. Document run/deploy commands and the data refresh procedure.

## Acceptance criteria

- `/healthz` and `/predictions` respond with CORS.
- Predictions return model vs ZTM fields and a gated flag.
- MAE on a recent slice is ~56.5 s gated (57.2 s raw), not ~86 s.
- Feature parity check against `eval_model.py` passes.
- Service handles feed outages and returns a clear health state.
- README has run/deploy instructions.
