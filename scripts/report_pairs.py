"""Dump every out-of-sample (forecast, outcome) pair from the nine-season
rolling backtest to data/report_pairs.csv for the accuracy report. Same folds,
training rules, and anchor blending as backtest.py; the only difference is
that per-pair rows are saved instead of just summary quantiles.

Columns: t (base time), h (lead hours), y (obs degC), p50/p05/p95 (anchored
predictions degC), persist (degC), fold. Plus the buoy/weather context at the
base time needed for conditional analysis: wspd, airwater (fut window means).
Runtime ~30-40 min (9 folds x 3 quantile fits)."""

import pathlib
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import featuresq

TAU = 8.0

buoy = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
wx = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)
X, y, t, h = featuresq.stack(buoy, wx)
yv = y.to_numpy()

folds = []
for year in [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]:
    in_year = t[(t.year == year)]
    if len(in_year) == 0:
        continue
    wend = in_year.max()
    folds.append((str(year), wend - pd.Timedelta(days=45), wend))
folds.append(("2026", t.max() - pd.Timedelta(days=35), t.max()))

rows = []
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
    decay = np.exp(-(hte - 1) / TAU)
    for q in pred:
        pred[q] = pred[q] + delta * decay

    df = pd.DataFrame({
        "t": tte, "h": hte, "y": yte,
        "p50": pred[0.5], "p05": pred[0.05], "p95": pred[0.95],
        "persist": persist, "fold": name,
        "wspd_fut": Xte["fut_wspd"].to_numpy(),
        "airwater_fut": Xte["fut_airwater"].to_numpy(),
        "v_fut": Xte["fut_v"].to_numpy(),
    })
    rows.append(df)
    print(f"fold {name}: {len(df)} pairs", flush=True)

out = pd.concat(rows, ignore_index=True)
out.to_csv("data/report_pairs.csv", index=False)
print(f"wrote data/report_pairs.csv: {len(out)} pairs")
