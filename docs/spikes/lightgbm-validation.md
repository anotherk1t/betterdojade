# LightGBM delay model — independent validation

**Date:** 2026-11-11  
**Scope:** read-only check of the exported LightGBM delay models against the newest data in the repo. No repository files were modified. All outputs are in this temp directory.

**Artifacts checked**
- `data/results/gdansk_clean/tree_delay_models_dir/delay_fullhist_model.txt`
- `data/results/gdansk_clean/tree_delay_models_dir/delay_coldstart_model.txt`
- `data/results/gdansk_clean/tree_delay_models_dir/tree_delay_encoders.json`
- `data/results/gdansk_clean/tree_delay_models/tree_models_metrics.json`
- `data/results/gdansk_clean/route_realtime_model_vs_ztm.csv`

**Environment:** Python 3.14 temp venv, `lightgbm 4.7.0`, `xgboost 3.4.1`, `pandas 3.1.1`, `numpy 2.5.4`. `libomp` was installed with Homebrew because the LightGBM/XGBoost macOS wheels need it. Models loaded without errors.

---

## Bottom line

1. **The 64.49 s claim is credible and reproducible.** On the cleaned-data holdout (departures 2026-04-21 → 2026-04-29) an independent LightGBM retrain scored **64.61 s MAE / 106.57 RMSE** vs ZTM **122.83 / 184.97**; the published file says 64.49 / 115.12. The model MAE matches to 0.12 s.
2. **The model also holds up on genuinely newer data.** The exported artifact scored **62.47 s MAE / 106.43 RMSE** on departures **2026-05-01 → 2026-05-07** (422,170 rows, 18,157 events) vs ZTM **119.23 / 182.54**. A model retrained only through 2026-04-29 scored 63.58 / 109.70 on the same week. May 1–7 is therefore the best available unseen holdout, and performance did not degrade.
3. **The 64.35 s number is stale and methodologically weaker.** It comes from a 700k-row sample of only 2026-03-07/08, using a leaky split on `snapshot_ts` (the same event appears on both sides) and 19 features without `headsign`. It is reproducible (we got **64.79 s / 99.92 s baseline**, cutoff 2026-03-08 09:42:41.549, matching the JSON), but it is **not** a full-corpus result and should not be quoted alongside 64.49.
4. **Main caveat: `obs_total` is a future-information feature.** Offline it is the final observation count for the event; online the service can only use the current count. Substituting the online value raises MAE from **62.47 → 85.98 s** on May 1–7 (and 62.88 → 86.55 on the 04-27 → 05-07 split). Retraining the same LightGBM with `obs_total = current count` restores **65.14 s**, so this is a train/serve skew, not a model-capacity problem.
5. **No data after 2026-05-07 15:34 UTC exists in the repo.** May 1–7 is the newest available slice. A longer post-training holdout is impossible without new collection.

---

## 1. Data actually available

| Artifact | Date range (UTC) | Rows / size | Notes |
|---|---|---|---|
| `data/estimations_remote/departures_*.json.gz` | 2026-03-07 10:29:18 → 2026-05-07 15:34:28 | 48,620 files, ~15 GB | Raw snapshots; ~90 s cadence from 2026-03-20, coarser (5–9 min) in early March |
| `departures_clean_staging.sqlite` | 2026-03-07 10:29:18 → 2026-04-29 10:11:20 | 2,187,722 rows | Deduplicated to one row per event; 1,655,446 REALTIME + 532,276 SCHEDULED; 94 routes, 1,678 stops, 114,135 trips |
| `gdansk_departures_realtime_model.csv.gz` | 2026-03-07 10:29:18 → 2026-04-29 10:11:20 | 1,649,557 rows | One row per valid realtime event |
| `gdansk_all_departures.csv.gz` | same window | 25,862,748 rows | Long-format raw departures |
| `route_realtime_model_vs_ztm.csv` | validation tail of cleaned window | 594,080 val rows | Published 64.49 / 115.12 |

**Training/validation window of the exported artifact (inferred):** `tree_delay_encoders.json` says `trained_rows = 2,970,397`. Rebuilding the feature cache over the cleaned window 2026-03-07 → 2026-04-29 at the same event-sampling rate produced **2,924,879 rows** (98.5% of the artifact's count), and the 80/20 departure split produced **584,964 val rows** vs the published **594,080** (98.5%). The published route-level MAEs correlate 0.85 (model) / 0.92 (ZTM) with our rebuild. This strongly indicates the artifact was trained through **2026-04-29**, with its published holdout being **2026-04-21 → 2026-04-29**.

**Newer slice:** raw snapshots 2026-05-01 → 2026-05-07 were not in the cleaned window and are the only newer data. If the artifact's cache accidentally included a few May rows, the effect is small: the exported model and a model retrained strictly through 04-29 differ by only 1.1 s MAE on that week.

---

## 2. Evaluation method

Feature construction is identical to `dev_tools/scripts/backtest_lead_time_stratified.py` and `delay_service.py`:

- REALTIME departures only, Gdansk route whitelist, midnight-wrap delay normalization, `-1200 ≤ delay ≤ 3600`, `0 ≤ lead_time ≤ 60 min`.
- Event key `(trip, stop_id, theoreticalTime)`; target = last observed delay before departure.
- 20 features: route/stop/vehicle_service/headsign label encodings, lead time, hour/dow cyclic terms, current/prev1/prev2 delay, deltas, 3-observation mean/std, `obs_index`, `obs_total`.

A windowed cache was built from **45,701 raw snapshots** with deterministic **2% event sampling** (CRC32 of the event key, all observations kept for each selected event): **3,233,195 rows / 139,328 events**, departures 2026-03-19 00:00 → 2026-05-07 16:21 UTC. Event sampling preserves complete histories and avoids the memory/IPC cost of the full ~175M-row corpus; the 64.61-vs-64.49 reproduction confirms it is representative.

Splits used:

1. **New-data holdout:** all departures 2026-05-01 → 2026-05-07 (422,170 rows, 18,157 events), scored with the exported artifact as-is.
2. **Time split:** 80/20 by departure time on the 03-19 → 05-07 cache; cutoff 2026-04-27 20:05; train 2,586,565 / val 646,630. LightGBM and XGBoost were retrained on train only with the repository's hyperparameters.
3. **Published 64.49 reproduction:** cache 03-07 → 04-29, 80/20 departure split; cutoff 2026-04-21 11:45; val 584,964 rows.
4. **Published 64.35 reproduction:** 700k sample of 03-07/08, leaky `snapshot_ts` split, 19 features, cutoff 2026-03-08 09:42:41.549.

Baseline is **ZTM passthrough**: predict the current observed delay. For the cold-start model the baseline is 0 (assume on-time).

---

## 3. Results

### 3.1 Overall MAE / RMSE

| Evaluation | Rows | LightGBM MAE | LightGBM RMSE | XGBoost MAE | XGBoost RMSE | ZTM MAE | ZTM RMSE |
|---|---:|---:|---:|---:|---:|---:|---:|
| **New data 2026-05-01 → 05-07** (exported artifact) | 422,170 | **62.47** | **106.43** | — | — | 119.23 | 182.54 |
| New data, retrained only through 04-29 | 422,170 | 63.58 | 109.70 | 63.31 | 110.00 | 119.23 | 182.54 |
| **Time split 04-27 → 05-07** (honest retrain) | 646,630 | **64.29** | **108.59** | **63.66** | **108.28** | 120.00 | 183.09 |
| Published holdout 04-21 → 04-29 (reproduction) | 584,964 | **64.61** | **106.57** | — | — | 122.83 | 184.97 |
| Published file (`route_realtime_model_vs_ztm.csv`) | 594,080 | 64.49 | 110.87 | — | — | 115.12 | 178.37 |
| Early 03-07/08 claim reproduction (leaky split) | 137,459 | 64.79 | 96.82 | — | — | 99.92 | 146.79 |
| Published `tree_models_metrics.json` (same early split) | 137,442 | 64.35 | 95.49 | 67.49 | 99.13 | 99.71 | 146.39 |

Additional baselines on May 1–7: zero-delay MAE 115.83 / RMSE 250.74; cold-start model 95.16 / 168.10. Applying the service's `|current_delay| > 1200 s → passthrough` gate improves the exported model slightly to **62.09 / 107.25**.

### 3.2 MAE by lead-time bucket — May 1–7, 2026 (exported artifact)

| Lead time | Rows | LightGBM MAE | ZTM MAE | Gain |
|---|---:|---:|---:|---:|
| 0–5 min | 37,831 | **31.86** | 36.34 | +4.48 |
| 5–15 min | 107,000 | **50.72** | 78.51 | +27.79 |
| 15–30 min | 147,236 | **68.33** | 130.52 | +62.19 |
| 30–60 min | 130,103 | **74.40** | 164.05 | +89.65 |

The independent 04-27 → 05-07 time split shows the same shape: 32.65 / 52.02 / 70.59 / 76.65 vs ZTM 36.37 / 78.57 / 131.47 / 166.14. The model's advantage grows with lead time, which is the useful regime for the dashboard.

### 3.3 Route-level results — May 1–7 (top routes by volume)

| Route | Rows | LightGBM MAE | ZTM MAE | Gain | Win? |
|---|---:|---:|---:|---:|---|
| 2 | 26,760 | 45.14 | 144.61 | +99.47 | yes |
| 6 | 18,296 | 47.05 | 127.94 | +80.89 | yes |
| 8 | 14,957 | 35.61 | 120.73 | +85.12 | yes |
| 199 | 14,911 | 64.49 | 112.53 | +48.04 | yes |
| 12 | 13,943 | 48.22 | 117.77 | +69.55 | yes |
| 10 | 13,766 | 48.61 | 124.81 | +76.20 | yes |
| 3 | 13,205 | 41.61 | 101.47 | +59.86 | yes |
| 127 | 12,802 | 81.70 | 159.51 | +77.81 | yes |
| 115 | 12,620 | 68.94 | 137.44 | +68.50 | yes |
| 5 | 11,628 | 41.57 | 121.50 | +79.93 | yes |

**91 of 92 routes beat ZTM** in the May 1–7 slice; the only loss is route **N16** (276 rows, 77.13 vs 72.10, −5.03 s). The 04-27 → 05-07 time split is also 91/92, with route **131** the only loss (1,294 rows, 119.06 vs 114.35, −4.71 s). The 04-21 → 04-29 published-window reproduction is 90/92, with losses on **131** (818 rows) and **267** (339 rows). All losses are low-volume routes; there is no broad route-level failure.

### 3.4 The `obs_total` train/serve skew

`obs_total` is the **final** number of observations for an event in training/backtest, but the live service only knows the count so far (`obs_total = len(hist)` in `delay_service.py`).

| Scenario | MAE | RMSE |
|---|---:|---:|
| Exported model, May 1–7, offline `obs_total` | 62.47 | 106.43 |
| Exported model, May 1–7, online `obs_total = obs_index + 1` | **85.98** | 140.52 |
| Exported model, 04-27 → 05-07 split, offline | 62.88 | 105.28 |
| Exported model, 04-27 → 05-07 split, online approximation | **86.55** | 139.91 |
| Retrained model, 04-27 → 05-07 split, offline | 64.29 | 108.59 |
| Retrained model, 04-27 → 05-07 split, online approximation | **88.44** | 143.58 |
| Same LightGBM retrained with `obs_total = obs_index + 1` (04-27 → 05-07 split) | **65.14** | — |
| Same LightGBM retrained without `obs_total` (04-27 → 05-07 split) | **65.12** | — |
| Same LightGBM retrained with `obs_total` capped at 12 (04-27 → 05-07 split) | **65.17** | — |

The live degradation is concentrated at long lead times: on May 1–7 the 15–30 min bucket goes 68.33 → 83.75 and the 30–60 min bucket goes 74.40 → 132.16, while 0–5 min is essentially unchanged (31.86 → 32.20). This is exactly the pattern expected from a feature that proxies how much history the event will eventually have. `obs_total` is not a minor feature: it ranks 6th by gain (2.18e10) and is used in 2,024 splits in the exported model.

**Actionable fix:** retrain the full-history model with the online definition of `obs_total` (or drop the feature). The same-family retrain recovers 65.14 s, only 0.85 s worse than the offline 64.29 s. This is a one-line feature change, not a new model family.

---

## 4. Comparison with the claimed numbers

| Claim | What it actually is | Independent result | Verdict |
|---|---|---|---|
| **64.35 s vs 99.71 s** | 700k sample of 2026-03-07/08 only; 19 features; leaky `snapshot_ts` split | 64.79 s vs 99.92 s; cutoff matches to the millisecond | Reproducible, but **stale and leaky**; not a full-corpus result |
| **64.49 s vs 115.12 s** | Cleaned window 2026-03-07 → 04-29; event/departure split; val 04-21 → 04-29; 20 features | 64.61 s vs 122.83 s; 584,964 val rows; route MAE corr. 0.85/0.92 | **Confirmed** for the model; baseline is sample-dependent (115–123 s) |
| Dashboard “later snapshot” 64.49 / 115.12 | Same published backtest file | May 1–7: 62.47 / 119.23 | Model holds up / slightly improves on newer data |

The 64.35 and 64.49 numbers are **not measuring the same thing**: different date range, different feature set (19 vs 20), different split key (snapshot vs departure/event), and different baseline difficulty. Quoting them as a progression is misleading. The honest headline for the exported 20-feature model is **~64.5 s on the April holdout and ~62.5 s on the May week**, against a ZTM passthrough of **~119–123 s**.

---

## 5. Caveats

1. **`obs_total` is future information.** The 64.49 s offline number is not achievable live without retraining; the online approximation gives ~86 s. This is the single most important caveat. Our approximation uses the full event history (`obs_index + 1`); the real service primes only 12 snapshots and starts mid-event, so the live number could differ (likely similar or worse at 30–60 min leads).
2. **Target definition.** The target is the last observed delay before departure, not the delay at the exact scheduled time. Snapshot cadence is ~90 s, so the label has some timing noise. This matches the training/backtest definition, so comparisons are internally consistent.
3. **Event sampling.** The rebuilt cache keeps 2% of events (139k events) but all observations per event. This is statistically valid and reproduced the published model MAE to 0.12 s, but route-level numbers for low-volume routes (N16, 131) have small samples.
4. **Baseline sampling.** Our ZTM baseline is 119–123 s vs the published 115.12 s. The model MAE matches closely, so the relative gain in our sample is slightly larger (56–58 s vs 50.6 s). Do not treat the 115.12 s baseline as exact.
5. **Artifact leakage.** The exported encoders were fit on all rows (including the published val tail), and the artifact was retrained on 100% of the cache, so scoring it on the old val tail is mildly optimistic (62.88 vs 64.29 for a train-only model on the same 04-27 → 05-07 split). The May 1–7 result is the cleaner check; a model retrained strictly through 04-29 scores 63.58 there, within 1.1 s of the artifact.
6. **No newer data.** Raw collection stops at 2026-05-07 15:34 UTC. There is no post-May-7 holdout, so this validation cannot detect drift beyond one week.
7. **XGBoost is essentially tied.** 63.66 s on the April/May time split and 63.31 s on May 1–7, vs LightGBM 64.29 / 62.47. No evidence that LightGBM is uniquely better; the choice is fine but not decisive.
8. **Cold-start model** is much weaker (95.16 s on May vs 115.83 s assume-on-time). It is a route-planning model without realtime history, not a substitute for the full-history model.

---

## 6. Reproduction

All scripts and intermediate outputs are in this directory:

- `build_cache_fast.py` — windowed cache builder (2% deterministic event sample)
- `evaluate.py` — 80/20 departure-time retrain + exported artifact comparison
- `eval_may.py` — May 1–7 new-data evaluation, buckets, route table
- `repro_6435.py` — 700k / 03-07-08 / leaky snapshot-split reproduction
- `repro_6449_0429.py` — 03-07 → 04-29 / departure-split reproduction
- `obs_total_experiment.py` — online `obs_total` variants
- `eval_may_xgb.py` — XGBoost on the May slice
- `metrics.json`, `metrics_may.json`, `route_level_val.csv`, `route_level_may.csv`, `repro_6435.json`, `repro_6449_0429.json`, `obs_total_experiment.json`

Key commands (temp venv):

```bash
python build_cache_fast.py --start 2026-03-19 --end 2026-05-07 \
  --out cache_0319_0507.csv.gz --keep-pct 200 --workers 8
python evaluate.py
python eval_may.py
python repro_6435.py
python repro_6449_0429.py
python obs_total_experiment.py
```

No repository files were changed. The only system-level change was `brew install libomp` to satisfy the LightGBM/XGBoost macOS wheels.
