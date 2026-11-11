# Delay prediction service

Hosted LightGBM prediction API for departure delays.

## Context

- Validation: `docs/spikes/lightgbm-validation.md`
- Improvement report: `docs/spikes/predictor-improvement.md`
- Current service: `delay_service.py` (copied from `dev_tools/scripts/`)
- Predictor on the homeserver: `127.0.0.1:8091` (`/healthz`, `/predictions`)
- Model artifact: `services/delay/model/`
- Training pipeline: `services/delay/training/`

## Improved model

The serving artifact is a 38-feature LightGBM booster trained on Sep–Oct 2026 snapshots:

- `regression_l1` objective, 128 leaves, 2,500 trees, MAE metric.
- No `obs_total` feature, so there is no train/serve skew.
- Route, stop, vehicle-service and route×lead-bucket priors, plus observation-span and
  trend features. `obs_span_min` and `trend_per_min` need `(snapshot_ts, delay)` history.
- Artifact size is about 28 MB (`delay_l1_model.txt`).

| Window | Raw MAE | Gated MAE | ZTM MAE | Gain (gated) |
|---|---:|---:|---:|---:|
| 2026-10-25 … 2026-11-01 | 57.16 s | **56.47 s** | 90.03 s | +33.56 s (37.3 %) |
| 2026-05-01 … 2026-05-07 | 62.53 s | **62.13 s** | 119.15 s | +57.02 s (47.9 %) |

- **88 of 89 October routes win** against ZTM; the only loss is route 131.
- The 0–5 min lead bucket now **wins by 4.80 s** (28.03 s vs ZTM 32.82 s), so the old
  short-lead gate is no longer used.
- May is statistically unchanged versus the previous model, so the October gain does not cost
  out-of-time accuracy.

Recommended serving gates:

- Routes `131` and `N16` → ZTM.
- `|ZTM delay| > 1200 s` → ZTM passthrough.
- Do **not** gate lead times below 5 min.

## Must fix before hosting

The current `delay_service.py` builds the old 20-feature row and approximates `obs_total`
online, which raises MAE to ~86 s. The new artifact is **not a drop-in replacement**:

1. Store `(snapshot_ts, delay)` per observation, not only the delay list.
2. Compute `obs_span_min` and `trend_per_min` from that history.
3. Build the 19 base and 19 derived features in the order in
   `services/delay/model/training_config.json`.
4. Look up prior arrays by encoded route/stop/vehicle-service code.
5. Drop `obs_total`; use `obs_index` only.
6. Keep the `|ZTM| > 1200 s` passthrough and the `131` / `N16` route gate.

The full feature recipe is in `services/delay/model/README.md`; the builder is
`services/delay/training/features.py`.

## Tasks

1. Replace the feature builder in `delay_service.py` with the 38-feature version.
2. Expose `/healthz` and `/predictions` with CORS and a 60 s cache.
3. Add the route gate and ZTM fallback.
4. Deploy behind the personal website / Cloudflare Tunnel.
5. Update the delays dashboard and add monitoring.
6. Refresh the model monthly (vocab, priors, training config, gate routes).

## Acceptance

- `/healthz` and `/predictions` respond with CORS.
- Predictions return model vs ZTM fields.
- MAE on a recent slice is ~56.5 s gated (57.2 s raw), not ~86 s.
- Service survives feed outages and returns a clear health state.
- README documents run/deploy commands.
