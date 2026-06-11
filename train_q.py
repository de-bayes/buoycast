"""Train the probabilistic water-temp forecaster and produce every statistic
the site shows.

Model: one HistGradientBoostingRegressor per quantile (P5/25/50/75/95),
horizon-conditioned, trained on stacked (t, h) rows for h up to +168 h.

Validation: the last 35 days of base times are TEST; training stops 168 h
plus a day before the test start, so no stacked row straddles the split.
Persistence is scored per horizon. Calibration = empirical coverage of the
50% and 90% bands on test. Also: residuals, predicted-vs-actual sample,
permutation importance, and a +24 h hindcast trace for the site.

Writes models/q_*.joblib, models/qstats.json."""

import json
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

import featuresq

CF = 1.8
TEST_DAYS = 35
MAX_ITER = 500
REFIT_FULL = "--refit-full" in sys.argv  # after stats: refit on ALL data for production

buoy = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
wx = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)

X, y, t, h = featuresq.stack(buoy, wx)
t_end = t.max()
test_start = t_end - pd.Timedelta(days=TEST_DAYS)
train_end = test_start - pd.Timedelta(hours=168 + 24)
tr = t <= train_end
te = t >= test_start
print(f"stacked rows: {len(X)} · train {tr.sum()} · test {te.sum()} · gap keeps splits honest")

models = {}
for q in featuresq.QUANTILES:
    m = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=MAX_ITER,
                                      learning_rate=0.07, random_state=11)
    m.fit(X[tr], y[tr])
    models[q] = m
    joblib.dump(m, f"models/q_{int(q * 100):02d}.joblib")
    print(f"fit q{q:.2f}")

Xte, yte, hte = X[te], y[te].to_numpy(), h[te]
pred = {q: models[q].predict(Xte) for q in featuresq.QUANTILES}
persist = Xte["WTMP"].to_numpy()

# anchor blending: at forecast time we know the current observation, so shift
# the whole trajectory by (obs_now - model's +1h estimate), decaying with lead
# (tau fixed a priori at 8 h, the scale where raw model and persistence cross)
TAU = 8.0
tte = t[te]
m1 = hte == 1
delta_by_t = dict(zip(tte[m1].values, (persist[m1] - pred[0.5][m1])))
delta = np.array([delta_by_t.get(v, 0.0) for v in tte.values])
decay = np.exp(-(hte - 1) / TAU)
for q in featuresq.QUANTILES:
    pred[q] = pred[q] + delta * decay

stats = {"horizons": [], "n_train": int(tr.sum()), "n_test": int(te.sum()),
         "n_features": X.shape[1], "n_hours": int(buoy["WTMP"].notna().sum()),
         "seasons": "2016-2026", "test_days": TEST_DAYS}
for hz in featuresq.HSET:
    m = hte == hz
    if m.sum() < 50:
        continue
    err = (pred[0.5][m] - yte[m]) * CF
    perr = (persist[m] - yte[m]) * CF
    in90 = float(np.mean((yte[m] >= pred[0.05][m]) & (yte[m] <= pred[0.95][m])))
    in50 = float(np.mean((yte[m] >= pred[0.25][m]) & (yte[m] <= pred[0.75][m])))
    stats["horizons"].append({
        "h": hz,
        "mae": round(float(np.mean(np.abs(err))), 3),
        "mae_persistence": round(float(np.mean(np.abs(perr))), 3),
        "rmse": round(float(np.sqrt(np.mean(err ** 2))), 3),
        "bias": round(float(np.mean(err)), 3),
        "p90_abs_err": round(float(np.quantile(np.abs(err), 0.9)), 3),
        "cover90": round(in90, 3),
        "cover50": round(in50, 3),
        "band90_width": round(float(np.mean(pred[0.95][m] - pred[0.05][m])) * CF, 2),
        "n": int(m.sum()),
    })
    print(f"+{hz:>3}h  mae {stats['horizons'][-1]['mae']:.2f}F vs persist "
          f"{stats['horizons'][-1]['mae_persistence']:.2f}F · cover90 {in90:.2f} · cover50 {in50:.2f}")

# band calibration for publish: empirical quantiles of the ANCHORED median's
# residuals per horizon (deg C). These become the published band offsets, so
# bands start tight at short leads and widen exactly as the test errors did.
calib = {}
for hz in featuresq.HSET:
    m = hte == hz
    if m.sum() < 50:
        continue
    res_c = pred[0.5][m] - yte[m]
    calib[str(hz)] = {
        "e05": round(float(np.quantile(res_c, 0.05)), 4),
        "e25": round(float(np.quantile(res_c, 0.25)), 4),
        "e75": round(float(np.quantile(res_c, 0.75)), 4),
        "e95": round(float(np.quantile(res_c, 0.95)), 4),
        "band90_mean_c": round(float(np.mean(pred[0.95][m] - pred[0.05][m])), 4),
    }
stats["calib"] = calib

# residual histogram and pred-vs-actual sample at +24h
m24 = hte == 24
res = (pred[0.5][m24] - yte[m24]) * CF
counts, edges = np.histogram(res, bins=np.arange(-4, 4.25, 0.25))
stats["residuals24"] = {"edges": [round(float(e), 2) for e in edges], "counts": counts.tolist()}
idx = np.random.default_rng(7).choice(np.flatnonzero(m24), size=min(600, int(m24.sum())), replace=False)
stats["scatter24"] = [[round(float(yte[i] * CF + 32), 1), round(float(pred[0.5][i] * CF + 32), 1)]
                      for i in idx]

# permutation importance of the median model on a test subsample
sub = np.random.default_rng(7).choice(np.flatnonzero(te.to_numpy() if hasattr(te, "to_numpy") else te),
                                      size=min(4000, int(te.sum())), replace=False)
imp = permutation_importance(models[0.5], X.iloc[sub], y.iloc[sub], n_repeats=3, random_state=7)
order = np.argsort(imp.importances_mean)[::-1][:12]
stats["importance"] = [{"name": X.columns[i], "value": round(float(imp.importances_mean[i] * CF), 3)}
                       for i in order]

# hindcast trace: +24h median and 90% band against what actually happened
m = m24 & (Xte.index.to_numpy() == Xte.index.to_numpy())  # all 24h rows
t24 = t[te][m24] + pd.Timedelta(hours=24)
o = np.argsort(t24.values)
stats["hindcast24"] = {
    "time": [pd.Timestamp(v).isoformat() for v in t24.values[o]],
    "actual": [round(float(v * CF + 32), 2) for v in yte[m24][o]],
    "p50": [round(float(v * CF + 32), 2) for v in pred[0.5][m24][o]],
    "p05": [round(float(v * CF + 32), 2) for v in pred[0.05][m24][o]],
    "p95": [round(float(v * CF + 32), 2) for v in pred[0.95][m24][o]],
}

with open("models/qstats.json", "w") as fh:
    json.dump(stats, fh)
print("saved models/q_*.joblib and models/qstats.json")

if REFIT_FULL:
    # production models learn from everything, including the test window the
    # stats were scored on; the stats describe the procedure, not these fits
    for q in featuresq.QUANTILES:
        m = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=MAX_ITER,
                                          learning_rate=0.07, random_state=11)
        m.fit(X, y)
        joblib.dump(m, f"models/q_{int(q * 100):02d}.joblib")
        print(f"refit q{q:.2f} on all {len(X)} rows")
    print("production models refit on full data")
