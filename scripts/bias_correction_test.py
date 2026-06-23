"""Pre-registered experiment: does a live bias correction on the forecast CENTER
help the sustained warm-bias regime (2019, and the current cold-lake stretch)
without hurting calm seasons?

Signal: the trailing-W-hour mean SIGNED +24h error, known causally at launch
time (the +24h call launched at b resolves at b+24h), exactly the construction
backtest.trailing_recent_error uses for the band width, but signed instead of
absolute. Correction: shift the whole predictive distribution (median + both
fences) by -alpha * signal at the launch time.

Pre-registered ship criteria (decide BEFORE looking at numbers):
  1. Pooled +24h |bias| must drop materially (target: at least halved).
  2. Pooled +24h cover90 must move toward 0.90 (up from the under-covered base).
  3. No calm fold (2022, 2023, 2025) may get MORE than 0.05 F worse in +24h MAE.
Pick the smallest alpha that meets 1+2; reject if it violates 3."""

import os
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

# run from the repo root so `import featuresq` and the data/ paths resolve
# regardless of how this script is invoked
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

import featuresq

TAU = 8.0   # anchor decay, matches backtest.py / publish.py
CF = 1.8
CALM = {"2022", "2023", "2025"}
WINDOW_H = 48
ALPHAS = [0.0, 0.3, 0.5, 0.7, 1.0]


def trailing_signed_error(tte, hte, err, window_h):
    """Trailing mean SIGNED +24h error, causal (known at launch). Mirrors
    backtest.trailing_recent_error but keeps the sign."""
    b24, e24 = tte[hte == 24], np.asarray(err)[hte == 24]
    s = pd.Series(e24, index=b24).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    resolved = s.copy()
    resolved.index = resolved.index + pd.Timedelta(hours=24)   # when known
    rolled = resolved.rolling(f"{window_h}h").mean()
    recent = rolled.reindex(tte, method="ffill").to_numpy()
    return np.where(np.isfinite(recent), recent, 0.0)


buoy = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
wx = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)
X, y, t, h = featuresq.stack(buoy, wx)
yv = y.to_numpy()
i24 = featuresq.HSET.index(24)

folds = []
for year in [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]:
    in_year = t[(t.year == year)]
    if len(in_year) == 0:
        continue
    wend = in_year.max()
    folds.append((str(year), wend - pd.Timedelta(days=45), wend))
folds.append(("2026", t.max() - pd.Timedelta(days=35), t.max()))

# accumulate per-fold +24h arrays under each alpha
per_fold = []   # {name, base_resid(+24h), base_actual, lo, hi, signal}
for name, wstart, wend in folds:
    tr = t <= (wstart - pd.Timedelta(days=8))
    te = (t >= wstart) & (t <= wend)
    if te.sum() < 1000:
        continue
    models = {}
    for q in [0.05, 0.5, 0.95]:
        m = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=250,
                                          learning_rate=0.08, random_state=11)
        m.fit(X[tr], y[tr])
        models[q] = m
    Xte, yte, hte, tte = X[te], yv[te], h[te], t[te]
    pred = {q: models[q].predict(Xte) for q in models}
    persist = Xte["WTMP"].to_numpy()
    m1 = hte == 1
    delta_by_t = dict(zip(tte[m1].values, persist[m1] - pred[0.5][m1]))
    delta = np.array([delta_by_t.get(v, 0.0) for v in tte.values])
    decay = np.exp(-(np.asarray(hte) - 1) / TAU)
    for q in pred:
        pred[q] = pred[q] + delta * decay

    resid = pred[0.5] - yte
    signal = trailing_signed_error(tte, np.asarray(hte), resid, WINDOW_H)

    mh = np.asarray(hte) == 24
    per_fold.append({
        "name": name,
        "med": pred[0.5][mh], "lo": pred[0.05][mh], "hi": pred[0.95][mh],
        "actual": yte[mh], "signal": signal[mh],
    })
    print(f"fold {name}: {int(mh.sum())} +24h pairs · raw bias {np.mean(resid[mh])*CF:+.2f}F")

print("\n+24h results by alpha (W=%dh).  bias/MAE in deg F.  cov target 0.90" % WINDOW_H)
print(f"{'alpha':>5} {'|bias|':>7} {'MAE':>6} {'cov90':>6}   per-calm-fold MAE delta vs alpha=0")
base_calm = {}
for a in ALPHAS:
    biases, maes, covs = [], [], []
    fold_mae = {}
    for f in per_fold:
        corr = a * f["signal"]
        med = f["med"] - corr
        lo = f["lo"] - corr
        hi = f["hi"] - corr
        err = (med - f["actual"]) * CF
        biases.append(np.mean(err))
        mae = np.mean(np.abs(err))
        maes.append(mae)
        covs.append(np.mean((f["actual"] >= lo) & (f["actual"] <= hi)))
        fold_mae[f["name"]] = mae
    if a == 0.0:
        base_calm = dict(fold_mae)
    # pooled (n-weighted would be better but folds are similar size)
    pooled_bias = np.mean(biases)
    pooled_mae = np.mean(maes)
    pooled_cov = np.mean(covs)
    calm_delta = "  ".join(f"{c}:{fold_mae[c]-base_calm[c]:+.2f}" for c in sorted(CALM) if c in fold_mae)
    print(f"{a:>5.1f} {abs(pooled_bias):>7.2f} {pooled_mae:>6.2f} {pooled_cov:>6.2f}   {calm_delta}")

print("\nper-fold +24h bias (F) and MAE (F) across alpha:")
hdr = "fold  " + " ".join(f"a={a:.1f}".rjust(13) for a in ALPHAS)
print(hdr)
for f in per_fold:
    cells = []
    for a in ALPHAS:
        corr = a * f["signal"]
        err = (f["med"] - corr - f["actual"]) * CF
        cells.append(f"{np.mean(err):+.2f}/{np.mean(np.abs(err)):.2f}")
    tag = "*" if f["name"] in CALM else " "
    print(f"{f['name']}{tag} " + " ".join(c.rjust(13) for c in cells))
print("(* = pre-registered calm fold; cells are bias/MAE)")
