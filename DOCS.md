# Seiche engineering notes

Running log of non-obvious decisions and the bugs behind them. Newest first.

## 2026-06-23 — Live bias correction on the forecast center

**Symptom.** The live 30-day track record degraded badly during a sustained
cold-lake stretch: +24h MAE 2.72F (worse than persistence's 1.54F), cover90
collapsed to 0.63, and a one-sided warm bias of +2 to +3F at every lead. The
model kept calling ~64F while the buoy sat at ~59F. A retrain did NOT fix it
(Sunday's refit on fresh data left the bias intact): it is structural, not a
stale model. The perfect-prog model maps weather to water, and in an upwelling
regime the surface is colder than the weather implies; even the LMHOFS physics
stream read ~67F vs the buoy's 59F, so it reinforced the warm call.

**Why the obvious fixes don't apply.** A retrain relearns the same warm mapping.
The reactive trend-nudge was already tested and rejected (2026-06-14) for a
different reason (the model already reacts to live *trends*); this is a
persistent *level* offset, not a trend. Symmetric band-widening (the adaptive
scale, already maxed at 2.5) can't fix a one-sided miss: the actuals all land on
the cold side of a too-warm median.

**Fix — damped trailing-bias correction (`publish.py`).** Track the trailing-48h
mean SIGNED +24h error (the same causal construction the band width uses, but
keeping the sign), and subtract a damped fraction from the median:
`corr(h) = clip(ALPHA * recent_bias * (1 - anchor_decay(h)), +/-1.5C)`, ALPHA
0.5. The `(1 - decay)` ramp keeps short leads pinned to the measured current
temperature (the anchor already makes +1h ~unbiased) and grows the correction in
as the anchor fades; the bands ride along with the shifted center. Exposed as
`data.json.bias_shift_f` (the +24h shift in F). This is a publish-time change
only -- no retrain, no model change.

**Validation** (`scripts/bias_correction_test.py`, pre-registered, 9 folds). The
backtest is perfect-prog (reanalysis weather), so it UNDERSTATES the live benefit
(it lacks the weather-driven warm bias) but tests the mechanism honestly: ALPHA
0.5 cuts pooled +24h |bias| 0.34 -> 0.16F and pooled MAE 0.93 -> 0.82F, with the
sustained-miss 2019 fold improving most (MAE 1.95 -> 1.29F, bias -1.49 ->
-0.77F). Cost in calm folds is small (2022 better, 2025 flat, 2023 +0.07F at
ALPHA 0.5 -- it ticks just over the pre-registered 0.05F guard, accepted as a
monitored tradeoff given the live regime is far more severe than any calm fold).
Live now: recent +24h bias +2.11F -> center cooled 1.00F at +24h.

**Invariant.** The correction must stay graceful and bounded: no recent resolved
+24h forecasts -> `recentbias` is None -> zero shift (forecast unchanged); the
shift is clipped to +/-1.5C so a pathological signal can't run the forecast away;
and it is zero at +1h (anchored to observation) by the `(1 - decay)` ramp. The
forecast log records the corrected (published) numbers, so the Track Record
scores what users actually saw and ALPHA can be retuned from live evidence. The
backtest calib is NOT yet re-derived on corrected residuals (a known
simplification); the adaptive band scale self-tightens as the logged error falls.

## 2026-06-19 — Retrain moved to the Mac (the micro is too slow), ships to VM

**Symptom.** The weekly VM retrain (`seiche-retrain.timer`) timed out twice: at
the old 2h cap, then again at a raised 4h cap (consuming 2h18m CPU at ~58% duty
on the throttled shared core, killed in the tail). The models *did* refresh
mid-run each time, but the chain never completed, risking half-updated state.

**Root cause.** The e2-micro is ~25x too slow for the streamed retrain. The
55-feature + subsurface-stream feature matrix over ~600k rows is rebuilt
independently by `train_q`, `backtest`, and `corr`; the journal showed a ~2h11m
gap from the stream fetch (17:48) to train_q's "stacked rows" (19:59) — feature
building alone, three times over, exceeds any sane timeout. More timeout cannot
fix a machine that slow; the honest fix is to retrain somewhere capable.

**Fix — Mac retrains, ships to the VM.** `scripts/retrain.sh` now runs the full
streamed chain on the Mac (~15 min: fetch + fetch_weather + stream updates +
`train_q --refit-full` + `backtest` + `corr`), then `gcloud compute scp`s the
artifacts the VM's `publish.py` reads — `q_*.joblib`, `qstats.json`,
`backtest.json`, `reports/correlations.json` — to a `/tmp` stage on the VM,
`install`s them as `buoycast:buoycast`, and triggers `seiche-publish.service`.
Mac and VM run identical libs (sklearn 1.8.0 / joblib 1.5.3 / numpy 2.4) so the
pickles load cleanly. Scheduled by the existing Mac launchd agent
`com.seiche.retrain` (Sun 05:30). The VM's `seiche-retrain.timer` is disabled.

**Invariant.** Serving/publishing stays always-on on the VM and never depends on
the Mac — `seiche-publish.timer` keeps shipping `data.json` every 10 min from
whatever models are installed. Only the *weekly model refresh* depends on the
Mac being awake roughly weekly; a missed week is harmless (the seasonal model is
stable week-to-week). The ship step must preserve `buoycast` ownership of
`/opt/seiche/models` (publish runs as that user) and must NOT overwrite the VM's
live-fetched stream CSVs (`data/mursst.csv`, `data/lmhofs.csv`) — publish
refreshes those itself, staleness-gated, and the Mac-trained model reads the
VM's live streams at inference.

## 2026-06-14 — Decision layer: swim, thresholds, alerts, beach

Turned the calibrated distribution into decisions (`decide.py` + `beach.py`,
wired through `publish.py` into `data.json`; dashboard panels in `site/`):
- **Swim guidance** (`decide.swim_comfort`): category + plain advice + cold-
  exposure guideline + wind/air exit caveat, for now and each of 7 days.
- **Threshold probabilities** (`decide.threshold_probs`): per-day P(water>=T)
  for 60/65/70F by linear-interp of the 5 calibrated quantiles (clamped to
  [0.05,0.95]), averaged over the day's hours, + first-crossing days.
- **Alerts** (`decide.alerts`): swim-threshold-reached, sharp cooling/upwelling
  (>=4F median drop in ~4 days), swim-window-opening. Pushed to a free ntfy.sh
  topic (`SEICHE_NTFY_TOPIC`, default seiche-wilmette-45174-lkmi), deduped via
  data/alert_state.json, no-auth, graceful.
- **Beach** (`beach.py`): a Ridge nearshore forecast (buoy + diurnal/seasonal +
  solar + recent beach-buoy gap), LOYO MAE 1.04F vs 2.19 naive, climatology
  fallback + 1.55x wider bands when no fresh reading. HONEST: it's the Ohio St
  Chicago-shelf sensor ~25km south, a proxy, not Wilmette; labeled as such.
  Integration gotcha: `_train()` reads the FULL data/buoy.csv (publish passes
  only ~45d realtime, too thin for the ~800h MIN_TRAIN overlap).

**Invariant.** Every block is optional: a missing/empty `swim/thresholds/beach/
alerts` must render nothing and never crash the page or the publish. Beach
returns [] (section hidden) when chibeach is missing/thin.

## 2026-06-14 — Subsurface streams promoted (tighter upwelling-tail bands)

The long-lead worst case is upwelling / fall turnover: a sudden cold crash
(2020-09-20 dropped ~16°F) the surface buoy can't anticipate a week out, where
the model regresses to the mean and runs too warm. Two cheap fixes failed first
(don't redo): a reactive trend-nudge (`scripts/trend_nudge.py` — the model
already reacts to live cooling; in active drops it's already slightly too cold),
and physics anticipation features built from surface data (`upwelling_features.py`
— corr with the tail ~0.00). The events need information below the surface.

The MUR satellite basin SST + NOAA LMHOFS 3D lake-physics model provide it. On
stream-covered long-lead rows (`scripts/streams_band.py`): worst-decile MAE
4.2 → 3.4°F, pinball loss ~10% lower, median better, overall MAE essentially
flat. LMHOFS is the driver; satellite adds a bit and is the reliable live floor.
They were rejected before (`validate_streams2`) only because that test scored
MEDIAN MAE, which the easy short leads dominate; on the tail / 90% band they win.

Promoted into `featuresq` (`stack` + `inference_rows` attach SAT+PHYS via
`streams.py`, graceful NaN, lazy import to avoid a cycle). Retrained the quantile
models (`lmhofs_fut` + `sat_basin` now rank top) and regenerated `calib_norm`.
`publish.py` and the retrain chain refresh the streams live, staleness-gated
(`fetch_mursst.update`, `fetch_lmhofs.update`).

**Invariant.** A stream fetch failure must NEVER crash the pipeline: missing
stream data falls back to NaN and the model degrades to surface-only. The
backtest `cover_diag` must still hold ~0.90 per fold (it does: adaptive spread
0.036). If the live LMHOFS fetch is down for long, bands run slightly tight
until the adaptive scale compensates.

## 2026-06-13 — Live Track Record (forecast logging + verification)

A self-scoring track record: every forecast `publish.py` ships is appended to
`data/fc_log.jsonl` (per-lead P5-P95 + the persistence baseline), and `verify.py`
joins each logged forecast to the observed water temperature as it resolves,
writing `site/verify.json` (rolling-30d MAE / coverage / bias / skill-over-
persistence by lead, plus a recent +24h forecast-vs-actual series). The page is
`site/track.html`. Routed like the other JSON: `verify.json` is in
`site/.vercelignore`, rewritten to the VM proxy in `site/vercel.json`, and in the
Caddy `@data` matcher.

Honesty notes that matter:
- The log records the *actually published* numbers, so the live track record
  captures weather-forecast error too, not just the model's perfect-prog error.
  It is the honest ground truth and accumulates over time.
- `seed_verify.py` reconstructs ~21 days into the log tagged origin `hindcast`
  so the page is not empty on day one. Reconstruction uses the current weekly
  model, which has trained on data inside that window, so its errors run
  optimistic (the seed showed ~0.63F at +24h vs the backtest's ~0.9F). The page
  labels hindcast vs live and the 9-season backtest remains the rigorous claim.
- `data/` is gitignored: the log lives on the VM, regenerated by seed + publish.

## 2026-06-12 — Adaptive band calibration (fixed regime-year under-coverage)

**Symptom.** The 90% band held ~0.90 marginally but its coverage swung wildly by
season: the rolling backtest showed 0.97-0.98 in calm years (bands too wide) and
**0.75 in 2019** (bands far too narrow). One static per-horizon width cannot be
right in both a placid October and a turnover-driven one.

**Root cause.** The published residual half-width was a single pooled
split-conformal quantile per horizon (`backtest.json` `calib`). Split conformal
is only *marginally* valid: it guarantees ~90% over the whole pool, not within
any particular regime. The weather-ensemble term in `publish.py` already
breathed with conditions, but the model-residual term was frozen, so when the
model itself blew out (a regime the features could not anticipate, e.g. 2019)
nothing widened.

**What did NOT work, and why we did not ship it.**
- *Volatility-conditioned bands* (std of the WTMP lag ladder, Mondrian terciles).
  Volatility tracks |error| only +0.22 and, critically, 2019 was a *level/regime*
  miss, not a choppy-water year (its volatility sat in the middle tercile). It
  cut coverage spread only 0.082 -> 0.071 and left 2019 at 0.74. See
  `featuresq.regime_signal` (kept for the analysis scripts) and
  `scripts/band_signal_panel.py`.
- *MUR satellite / LMHOFS physics as a median anchor.* Already rejected by the
  pre-registered `validate_streams2.py` (sat_lean +0.022F but 5/9 wins and a
  -0.056F worst fold; phys_lean +0.016F, 3/7). We did not override that result.
  Once the adaptive scale below fixed the 2019 under-coverage these streams were
  meant to catch, a satellite band-conditioner became redundant complexity too.
- *Linear (lasso/quantile) center model.* The old per-horizon `compare.py`
  favored lasso, but in the production stacked/quantile/weather setup HGB beats
  it at ~every horizon (MAE +0.29F, pinball +0.086F worse for linear), so the
  center stays HGB. See `scripts/lasso_quantile_bakeoff.py`.

**Fix — adaptive normalized conformal (ACI-style).** Normalize each residual by
a live *difficulty* signal before conformalizing: the trailing-48h mean of the
realized +24h error vs the typical level the backtest measured. A run of bad
calls (a regime shift) stretches the bands; a calm run tightens them.
- `backtest.py` conformalizes the **scaled** residuals per horizon and writes
  `calib_norm = {ref, clip, horizons}` (quantiles in scale units) alongside the
  static `calib` (still the fallback).
- `publish.py` rebuilds the same difficulty signal live from its last-48h
  resolved +24h forecasts, divides by `ref`, clips to `[0.5, 2.5]`, and
  re-inflates the residual half-width by that scale (still combined in
  quadrature with the ensemble spread). Exposes it as `data.json.band_scale`.

**Validation** (`scripts/band_method_compare.py`, 131,745 pairs / 9 folds):
recent-error normalization beat volatility, |median-persistence|, and a blend.
Per-fold cover90 spread **0.082 -> 0.028**, 2019 **0.75 -> 0.93**, worst fold
0.75 -> 0.83; calm-year bands get *sharper* (2025 3.6F -> 2.9F) while regime-year
bands widen (2019 3.6F -> 5.7F). Median forecast and MAE are unchanged — this
touches only the band, not the point estimate.

**Invariant.** The published 90% band must cover ~0.90 *within each backtest
fold*, not merely pooled. `backtest.py` prints the per-fold static-vs-adaptive
coverage every run and stores it in `backtest.json.cover_diag`; the adaptive
spread should stay well under the static spread (currently 0.028 vs 0.082) and no
fold should fall below ~0.83. If a future fold under-covers in a way the
recent-error scale does not catch, revisit the difficulty signal (the satellite
basin-divergence idea is the first thing to try) before widening blindly.
