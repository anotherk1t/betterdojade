# LightGBM delay predictor — improvement on the newest data

**Date:** 2026-11-11
**Compute:** Apple M1 Max, 10 cores, 64 GB RAM (all feature building, training and evaluation local)
**Data host:** `yan@192.168.0.129`, `/home/yan/bikerouter/data/estimations` (snapshot archive)
**Artifacts:** `services/delay/model/` (booster, priors, vocab, training config, gate routes) and
`services/delay/training/` (pipeline scripts).

---

## Bottom line

A retrained LightGBM with **L1 objective, stop/route/vehicle-service priors and explicit trend
features**, and **no `obs_total`**, reaches **57.16 s MAE on 2026-10-25 … 2026-11-01** versus
**67.51 s for the current model** and **90.03 s for ZTM**.

- **−10.36 s MAE (−15.3 %) versus the current model** on the newest complete week.
- **+32.87 s (36.5 %) better than ZTM**, up from +22.51 s (25.0 %).
- With the recommended serving gates (route 131/N16 + `|ZTM| > 1200 s`) it reaches
  **56.47 s on October** and **62.13 s on May**.
- **88 of 89 routes win** (current model: 67 of 89); the only loss is route 131 (−6.94 s).
- The old **0–5 min loss becomes a win**: 35.24 → **28.03 s** vs ZTM 32.82 s (+4.80 s).
- On **2026-05-01 … 2026-05-07** the new model is **62.53 s**, statistically identical to the
  current model's 62.57 s and the published 62.47 s. So the October gain does **not** cost May
  accuracy.
- **Winning change:** switching the objective to **`regression_l1`** (−2.87 s on the same rows),
  plus the prior/trend feature block (−2.13 s) and dropping `obs_total` (which adds nothing
  online and removes the train/serve skew).

---

## 1. Data and split

| Item | Value |
|---|---|
| Raw snapshots | `departures_*.json.gz`, ~947 files/day, ~90 s cadence |
| Training fit window | **2026-09-01 00:00 → 2026-10-22 00:00 UTC** (fit through 21 Oct) |
| Early-stopping window | **2026-10-22 → 2026-10-25** (3 days, never used for fitting) |
| Primary holdout | **2026-10-25 00:00 → 2026-11-01 00:00 UTC** (7 days) |
| Secondary holdout | **2026-05-01 → 2026-05-08 UTC** (7 days, fully out-of-time) |
| Rows, primary holdout | 16,740,957 rows / 1,012,562 events |
| Rows, May holdout | 22,047,451 rows / 942,641 events |
| Training rows (before sampling) | 8,260,722 (Sep 1–Oct 21) |
| Training rows used | 5,999,474 event-sampled rows / 361,999 events |
| Priors | computed from all 8,260,722 training rows (Sep 1–Oct 21) only |

The row/event counts reproduce the previous validation report exactly
(16,740,957 / 1,012,562 and 22,047,451 / 942,641), which validates the extraction.

**No leakage.** Training events are `theo_day < 2026-10-22`; the primary holdout starts
`2026-10-25`; May 1–7 is never used in any fit step. Priors and encoders are built from
pre-holdout data only. The 3-day early-stopping slice is inside the training dump but is
excluded from the fit.

> Note: raw extraction (`dump_rows.py`) was done on the homeserver during the initial data-prep
> phase, before the compute-local constraint. All feature building, training, evaluation and
> report generation ran on the Mac. No model training or evaluation ran on the homeserver.

---

## 2. Pipeline validation

The existing exported model (`delay_fullhist_model.txt`) was evaluated on the same local dumps
with the same row construction:

| Window | This run | Previous report |
|---|---:|---:|
| Oct 25–Nov 1, MAE | **67.5149 s** | 67.51 s |
| Oct 25–Nov 1, RMSE | 121.0861 s | 121.09 s |
| May 1–7, MAE | **62.5740 s** | 62.57 s |
| May 1–7, RMSE | 105.9952 s | 106.00 s |

The reproduction is exact to rounding, so the comparison below is apples-to-apples.

---

## 3. Experiments and results

All experiment metrics below are on the **internal early-stopping window Oct 22–24**
(492,981 rows, ZTM MAE 93.82 s), except the final rows which are the real holdouts.

### 3.1 Feature block and `obs_total`

4M event-sampled rows, 128 leaves, L2 objective, 1,200 rounds (same events for every row):

| Experiment | Features | Val MAE | Δ vs base19 |
|---|---|---:|---:|
| `base20_off` | 20 original + offline `obs_total` | 61.66 s | −0.56 |
| `base20_on` | 20 original + online `obs_count` | 62.23 s | +0.01 |
| `base19` | 19 original, no count feature | 62.22 s | — |
| **`rich`** | 19 + 19 prior/trend features, no count | **60.09 s** | **−2.13** |
| `rich_on` | rich + online `obs_count` | 60.14 s | −2.08 |

- The original `obs_total` only helps when it is the **offline final count** (61.66 vs 62.22).
- The **online** definition adds **nothing** (62.23 vs 62.22), and in the rich model it is also
  neutral (60.14 vs 60.09). **Dropping `obs_total` is the correct serving choice**; it removes
  the train/serve skew entirely.

### 3.2 LightGBM tuning

3M event-sampled rows, rich features, 2,000 rounds, early stopping 80:

| Params | Leaves | Objective | Val MAE |
|---|---:|---|---:|
| `p1_base` | 64 | L2 | 60.87 s |
| `p2_leaves128` | 128 | L2 | 60.54 s |
| `p3_leaves255` | 255 | L2 | 60.16 s |
| `p4_leaves128_l2` | 128 | L2, λ=5 | 60.38 s |
| `p5_leaves512` | 512 | L2 | **59.96 s** |
| `p6_small_lr` | 96 | L2, lr 0.02 | 60.83 s |
| `p2_l1` | 128 | **L1** | **57.67 s** |
| `p3_l1` | 255 | **L1** | **57.23 s** |

**The L1 objective is the single biggest win: −2.87 s** at identical features and rows
(60.54 → 57.67). More leaves help a little under L2 (64 → 512: −0.9 s) but are not worth the
runtime under L1; 128 leaves is the practical choice.

### 3.3 Final full-data runs

| Model | Train rows | Rounds | Internal val | Oct holdout | May holdout |
|---|---:|---:|---:|---:|---:|
| rich + L2 (`s1_rich`) | 4.0 M | 1,200 | 60.09 s | 60.60 s | 65.75 s |
| rich + L1 (`s2_p2_l1`) | 3.0 M | 1,998 | 57.67 s | 57.38 s | — |
| **rich + L1 fast (`final_all_p2l1fast`)** | **6.0 M** | **2,500** | **57.23 s** | **57.16 s** | **62.53 s** |

The final model used `max_bin=127` and `force_col_wise=True` for runtime; it matches the
255-leaf L1 model's internal score at a fraction of the cost (10.2 min on 10 cores).

### 3.4 Experiments not completed

- **Recency weighting** (half-life 90 d): the 3M-row run was too slow on the loaded machine and
  was stopped; no conclusion. Within Sep–Oct the weights only range 0.66–0.97, so the expected
  gain is small.
- **Lead-time specialist models** (0–5 / 5–15 / 15–30 / 30+): not run. The single rich model
  already wins every October bucket, so the upside is limited.
- **Two-stage route-residual model**: not run.
- **April 21–30 data**: parsed (2.4 M rows) as a long-lead coverage option, but the final model
  trains on Sep–Oct only; the May result shows no need for it.

---

## 4. Best model

**Artifacts:** `services/delay/model/` (`delay_l1_model.txt`, `priors.npz`, `vocab.json`,
`training_config.json`, `gate_routes.json`, `README.md`).

```
objective        regression_l1
learning_rate    0.05
num_leaves       128
min_child_samples 100
subsample        0.8, freq 1
colsample_bytree 0.8
reg_lambda       0.0
max_bin          127
force_col_wise   true
num_boost_round  2500 (best_iteration = 2500, cap reached)
metric           mae
seed             42
```

**Features (38):**

```
route, stop, vsvc, headsign,
lead_min, hour, dow, hour_sin, hour_cos, dow_sin, dow_cos,
current_delay, prev1, prev2, delta_prev1, delta_prev2,
hist_mean3, hist_std3, obs_index,
hist_mean5, hist_std5, obs_span_min, trend_per_min, lead_bucket,
route_mean_target, route_mean_corr, route_mean_current,
stop_mean_target, stop_mean_corr, stop_std_target,
vsvc_mean_corr, route_bucket_corr, global_bucket_corr,
current_minus_route_mean, current_plus_trend, hist_mean3_plus_trend,
route_corr_lead, stop_corr_lead
```

No `obs_total`. Categorical encoders refreshed from 13 pre-holdout days:
94 routes, 1,712 stops, 963 vehicle services, 155 headsigns.
Unknown rates on the October holdout: route 0 %, stop 0 %, vehicle service **0.70 %**,
headsign 0 %. On May: vehicle service 0.30 %, headsign 0.02 %.

Top gain features: `current_delay`, `stop_mean_target`, `hist_mean3`, `current_plus_trend`,
`stop_corr_lead`, `stop_std_target`, `lead_min`, `stop_mean_corr`, `hour`, `prev1`,
`vsvc_mean_corr`, `route_mean_target`. The stop-level priors are the strongest new signal.

---

## 5. Lead-time results (October 25–November 1)

| Lead bucket | Rows | Current MAE | **New MAE** | ZTM MAE | Current gain | **New gain** |
|---|---:|---:|---:|---:|---:|---:|
| 0–5 min | 2,188,832 | 35.24 | **28.03** | 32.82 | −2.42 | **+4.80** |
| 5–15 min | 6,160,165 | 57.45 | **48.84** | 71.73 | +14.28 | **+22.88** |
| 15–30 min | 8,390,393 | 83.29 | **70.84** | 118.34 | +35.05 | **+47.51** |
| 30–60 min | 1,567 | 234.12 | **175.26** | 316.90 | +82.78 | **+141.64** |

- The new model **wins the 0–5 min segment**; the old lead-time gate is no longer needed.
- 5–15 and 15–30 min improve by 8.6 s and 12.5 s respectively.
- With the recommended route + delay gate, overall October MAE is **56.47 s**; the bucket MAEs
  become 26.65 / 48.20 / 70.28 / 265.02 s. The 30–60 bucket worsens under the delay gate
  because the model is better than ZTM there, but it is only 1,567 rows.
- The October 30–60 bucket is still only 1,567 rows (0.009 %), so it is not a reliable estimate.

### May 1–7 (same model, fully out-of-time)

| Lead bucket | Rows | Current MAE | New MAE | ZTM MAE |
|---|---:|---:|---:|---:|
| 0–5 min | 1,971,354 | 31.66 | **29.73** | 36.38 |
| 5–15 min | 5,578,761 | 50.55 | **49.77** | 78.81 |
| 15–30 min | 7,683,671 | 68.75 | **68.69** | 130.85 |
| 30–60 min | 6,813,665 | 74.40 | **75.52** | 162.94 |

May is essentially tied overall (62.53 vs 62.57). Short leads improve, 15–30 is flat, and the
30–60 min bucket is 1.1 s worse. With the recommended route + extreme-delay gate, May improves
to **62.13 s** and the 30–60 bucket to **75.15 s** (still +0.75 s vs the current 74.40 s).
This is the expected cost of an L1/median objective on the long-lead tail and of training on a
regime with almost no >30 min rows.

---

## 6. Route-level results

### October 25–November 1

**88 of 89 routes win** (current model: 67/89). Only route **131** loses:

| Route | Rows | New MAE | ZTM MAE | Gain |
|---|---:|---:|---:|---:|
| 131 | 33,280 | 25.32 | 18.37 | **−6.94** |
| 176 | 41,846 | 31.98 | 32.01 | +0.04 |
| N16 | 5,396 | 79.90 | 80.75 | +0.85 |
| 269 | 77,118 | 35.04 | 38.19 | +3.15 |
| 123 | 88,315 | 41.53 | 45.42 | +3.89 |
| 166 | 40,630 | 39.80 | 44.00 | +4.19 |

Best routes: N9 +116.8 s, N1 +77.3 s, 267 +73.9 s, N3 +73.4 s, 7 +66.0 s, 11 +64.8 s,
2 +64.4 s, 12 +64.3 s. Per-route tables are produced by `eval_model.py`.

### May 1–7

**90 of 92 routes win.** Only N16 (−1.64 s) and 131 (−0.83 s) lose. Best: N5 +119.6 s,
N9 +102.1 s, 2 +98.1 s, N3 +89.6 s, 8 +86.9 s.

The October regression on routes 131/307/256/179 from the old model is gone; 131 remains the
one consistently hard route.

---

## 7. Gating

A route gate of **{131, N16}** was derived from the model's internal calibration window
(Oct 22–24), where both lost with ≥100 rows. Applying it to the October holdout:

| Variant | Oct MAE | Gain vs ZTM | May MAE | Gain vs ZTM |
|---|---:|---:|---:|---:|
| raw | 57.1567 s | +32.871 s | 62.5291 s | +56.623 s |
| route gate {131, N16} | 57.1432 s | +32.885 s | 62.5271 s | +56.625 s |
| `|ZTM| > 1200 s` gate | 56.4734 s | +33.554 s | 62.1234 s | +57.028 s |
| **route + delay gate (recommended)** | **56.4659 s** | **+33.562 s** | **62.1297 s** | **+57.022 s** |
| lead <5 min gate | 57.7838 s | +32.244 s | — | — |
| lead + route + delay | 57.2727 s | +32.755 s | 62.7930 s | +56.359 s |

- The route gate removes the only losing October route and improves MAE by 0.014 s.
- The extreme-delay gate **improves** MAE by 0.68 s on October and 0.41 s on May; keep it.
- **Do not gate lead <5 min** with the new model: it costs 0.63 s.
- Note: the delay gate makes the tiny October 30–60 min bucket worse (175 → 265 s, 1,567 rows)
  because the model beats ZTM there. Overall MAE still improves, and on May the 30–60 bucket
  improves slightly (75.52 → 75.15 s).

---

## 8. Recommendation for the hosted backend

**Ship the rich L1 model** (artifacts in `services/delay/model/`), after adding the feature builder to the
service. Expected production result on the current feed with the recommended gates:
**56.47 s MAE vs 67.5 s today** (−16.4 %), and **37.3 % better than ZTM** instead of 25.0 %.

Required service changes:

1. Store `(snapshot_ts, delay)` per event history (needed for `obs_span_min` and
   `trend_per_min`).
2. Build the 19 derived features from `priors.npz` and the encoded categoricals.
3. Drop `obs_total`; use `obs_index`/`obs_count` only.
4. Keep the `|ztm| > 1200 s` safety gate (it improves overall MAE by 0.68 s on October and
   0.41 s on May).
5. Gate routes `131` and `N16` to ZTM.
6. Remove the lead-time <5 min gate (the model now wins there).
7. Retrain monthly (or after a feed/cadence change): refresh the vocab and priors, then rerun
   this exact pipeline. Training is ~10 min on the Mac; extraction is ~1 min/day.

If the backend cannot yet store snapshot timestamps, the next-best option is to set
`trend_per_min = 0` and `obs_span_min = 0`; this loses part of the gain but keeps the prior
features. That variant was not separately measured.

---

## 9. Caveats and leakage checks

1. **Leakage checks passed.** Training fit uses `theo_day < 2026-10-22`; priors use the same
   rows; encoders use 13 days in Apr/Sep/Oct, all before the holdout. The October holdout
   starts 2026-10-25 and May 1–7 is never in any fit step. No target-derived feature touches a
   holdout event.
2. **Early-stopping carve-out.** Oct 22–24 is excluded from the fit and used only for early
   stopping. This is 3 days (≈0.5 M rows) less training data than a literal "fit through 24 Oct";
   retraining on them with a fixed round count would likely add a small gain.
3. **Round cap.** `best_iteration` hit the 2,500 cap; more rounds may help slightly.
4. **Row-weighted metrics.** Rows are correlated within events. Event-level MAE: October
   **57.61 s** (current 67.53 s, ZTM 88.12 s); May **63.73 s** (current 62.96 s, ZTM 112.02 s).
   The October conclusion is unchanged at event level; May is 0.8 s worse at event level.
5. **RMSE trade-off.** The L1 objective improves MAE but not RMSE: October 121.09 → 110.75 s
   (better), May 106.00 → 111.37 s (worse by 5.4 s). With the recommended gates: October
   110.66 s, May 111.42 s. If the product cares about large-error tails rather than typical
   error, blend with the L2 model or keep the current model for long-lead rows.
6. **May long-lead bucket.** 30–60 min is 1.1 s worse than the current model (75.52 vs 74.40),
   because the Sep–Oct training regime exposes almost no >30 min leads. The October feed also
   has almost none (1,567 rows), so this does not affect the current product.
7. **30–60 min October bucket is tiny** (0.009 % of rows); do not over-interpret.
8. **Recency weighting, lead-bucket specialists and two-stage models were not completed**
   within the timebox. The w90 run was stopped as inconclusive.
9. **Feature-builder parity.** The saved model is only valid with the exact 38-feature recipe in
   `services/delay/model/README.md`; the current `delay_service.py` 20-feature builder is not compatible.

---

## 10. Exact commands

Environment:

```bash
cd services/delay/training
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install lightgbm numpy        # lightgbm 4.6.0, numpy 2.0.2
```

Extraction (one-off data prep; raw snapshots are read from the data host, dumps stay local).
The previous exported model and encoders (`tree_delay_encoders.json`) are kept on the data host:

```bash
python dump_rows.py --start 2026-09-01T00:00:00 --end 2026-10-25T00:00:00 \
  --vocab ../model/vocab.json --old-encoders existing_model/tree_delay_encoders.json \
  --out dumps/train_sepoct.bin --event-rate 0.07 --workers 6
python dump_rows.py --start 2026-10-25T00:00:00 --end 2026-11-01T00:00:00 \
  --vocab ../model/vocab.json --old-encoders existing_model/tree_delay_encoders.json \
  --out dumps/val_oct.bin --event-rate 1.0 --workers 6
python dump_rows.py --start 2026-05-01T00:00:00 --end 2026-05-08T00:00:00 \
  --vocab ../model/vocab.json --old-encoders existing_model/tree_delay_encoders.json \
  --out dumps/val_may.bin --event-rate 1.0 --workers 6
```

Vocabulary (13 pre-holdout days):

```bash
.venv/bin/python scan_vocab.py \
  --days 2026-09-03,2026-09-10,2026-09-17,2026-09-24,2026-10-01,2026-10-08,2026-10-15,2026-10-20,2026-10-23,2026-10-24,2026-04-22,2026-04-25,2026-04-28 \
  --out vocab.json --workers 6
```

Best model:

```bash
.venv/bin/python train_exp.py \
  --dumps dumps/train_apr.bin dumps/train_sepoct.bin \
  --train-start 2026-09-01 --train-end 2026-10-22 --val-end 2026-10-25 \
  --config rich --params p2_l1_fast \
  --max-train-rows 6000000 --num-boost-round 2500 --early-stopping 80 --threads 10 \
  --priors-out out/priors.npz \
  --out-model out/delay_l1_model.txt --out-json out/training_config.json
```

`--train-start 2026-09-01` filters the April dump out of both the fit and the priors; it is
included only to keep the exact event-id ordering used for the saved model. Copy the three
outputs into `../model/` together with the refreshed `vocab.json` and `gate_routes.json`.

Evaluation (October, with and without the route gate; May):

```bash
.venv/bin/python eval_model.py --dump dumps/val_oct.bin \
  --model ../model/delay_l1_model.txt --config-json ../model/training_config.json \
  --priors ../model/priors.npz --vocab ../model/vocab.json \
  --out out/val_oct_final.json

.venv/bin/python eval_model.py --dump dumps/val_oct.bin \
  --model ../model/delay_l1_model.txt --config-json ../model/training_config.json \
  --priors ../model/priors.npz --vocab ../model/vocab.json \
  --gate-routes-json ../model/gate_routes.json --out out/val_oct_final_gated.json

.venv/bin/python eval_model.py --dump dumps/val_may.bin \
  --model ../model/delay_l1_model.txt --config-json ../model/training_config.json \
  --priors ../model/priors.npz --vocab ../model/vocab.json \
  --out out/val_may_final.json
```

Pipeline check with the previous model:

```bash
.venv/bin/python eval_model.py --dump dumps/val_oct.bin --model existing \
  --old-models-dir existing_model --vocab ../model/vocab.json --out out/val_oct_existing.json
.venv/bin/python eval_model.py --dump dumps/val_may.bin --model existing \
  --old-models-dir existing_model --vocab ../model/vocab.json --out out/val_may_existing.json
```

---

## Appendix: packaged artifacts

| File | Description |
|---|---|
| `services/delay/model/delay_l1_model.txt` | Best booster (2,500 trees, 128 leaves, L1, 28 MB) |
| `services/delay/model/training_config.json` | Training config, internal metrics, feature importance |
| `services/delay/model/priors.npz` | Prior arrays used by the best model |
| `services/delay/model/vocab.json` | Categorical vocabularies and unknown indices |
| `services/delay/model/gate_routes.json` | Route gate derived from the internal calibration window |
| `services/delay/model/README.md` | Serving artifact notes and 38-feature recipe |
| `services/delay/training/common.py` | Snapshot parsing, column layout, shared helpers |
| `services/delay/training/features.py` | Feature matrix and prior construction |
| `services/delay/training/dump_rows.py` | Snapshot → feature-row extraction |
| `services/delay/training/scan_vocab.py` | Categorical vocabulary scan |
| `services/delay/training/make_priors.py` | Prior computation for a date range |
| `services/delay/training/train_exp.py` | Training entry point |
| `services/delay/training/eval_model.py` | Holdout evaluation and gating |
| `docs/spikes/predictor-improvement-summary.json` | Machine-readable headline metrics |

Evaluation outputs (per-route tables, ablations, dumps, run logs) stay on the data host; they
are reproducible with the commands above.
