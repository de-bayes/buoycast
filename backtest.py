"""Rolling-origin backtest across five seasons. For each fold, the test
window is the final 45 in-season days of a year (35 for the current one);
training uses only data ending 8 days before the window, then P5/P50/P95
models are fit fresh and scored with the same anchor blending production
uses. Nothing from any test window ever touches its fold's training.

Writes models/backtest.json and reports/backtest.png."""

import json

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.ensemble import HistGradientBoostingRegressor

import featuresq

TAU = 8.0
CF = 1.8

buoy = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
wx = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)
X, y, t, h = featuresq.stack(buoy, wx)
yv = y.to_numpy()

folds = []
for year in [2022, 2023, 2024, 2025]:
    in_year = t[(t.year == year)]
    if len(in_year) == 0:
        continue
    wend = in_year.max()
    folds.append((str(year), wend - pd.Timedelta(days=45), wend))
folds.append(("2026", t.max() - pd.Timedelta(days=35), t.max()))

results = {"folds": [], "horizons": featuresq.HSET}
total_pairs = 0
for name, wstart, wend in folds:
    tr = t <= (wstart - pd.Timedelta(days=8))
    te = (t >= wstart) & (t <= wend)
    if te.sum() < 1000:
        print(f"fold {name}: too small, skipped")
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

    fold = {"name": name, "n": int(te.sum()), "train_n": int(tr.sum()),
            "window": f"{wstart:%Y-%m-%d} to {wend:%Y-%m-%d}", "mae": [], "mae_persist": [], "cover90": []}
    for hz in featuresq.HSET:
        m = hte == hz
        if m.sum() < 30:
            fold["mae"].append(None)
            fold["mae_persist"].append(None)
            fold["cover90"].append(None)
            continue
        fold["mae"].append(round(float(np.mean(np.abs(pred[0.5][m] - yte[m]))) * CF, 3))
        fold["mae_persist"].append(round(float(np.mean(np.abs(persist[m] - yte[m]))) * CF, 3))
        fold["cover90"].append(round(float(np.mean((yte[m] >= pred[0.05][m]) & (yte[m] <= pred[0.95][m]))), 3))
    results["folds"].append(fold)
    total_pairs += int(te.sum())
    at24 = fold["mae"][featuresq.HSET.index(24)]
    p24 = fold["mae_persist"][featuresq.HSET.index(24)]
    print(f"fold {name} ({fold['window']}): {fold['n']} pairs · +24h mae {at24}F vs persist {p24}F")

results["total_pairs"] = total_pairs
mean = lambda key, i: round(float(np.mean([f[key][i] for f in results["folds"] if f[key][i] is not None])), 3)
results["mean_mae"] = [mean("mae", i) for i in range(len(featuresq.HSET))]
results["mean_mae_persist"] = [mean("mae_persist", i) for i in range(len(featuresq.HSET))]
results["mean_cover90"] = [mean("cover90", i) for i in range(len(featuresq.HSET))]

with open("models/backtest.json", "w") as fh:
    json.dump(results, fh)

plt.style.use("dark_background")
BG, PANEL, INK, CYAN, FAINT = "#0a0c0e", "#101418", "#cfdce8", "#39c2ff", "#5d7283"
fig, ax = plt.subplots(figsize=(11, 5.6), facecolor=BG)
ax.set_facecolor(PANEL)
hs = featuresq.HSET
for f in results["folds"]:
    ax.plot(hs, f["mae"], color=CYAN, alpha=0.30, lw=1.1)
    ax.plot(hs, f["mae_persist"], color=FAINT, alpha=0.30, lw=1.1, ls="--")
ax.plot(hs, results["mean_mae"], color=CYAN, lw=2.6, marker="o", ms=4, label="model, 5-season mean")
ax.plot(hs, results["mean_mae_persist"], color=FAINT, lw=2, ls="--", label="persistence, 5-season mean")
ax.set_xlabel("lead time (hours)", color=INK)
ax.set_ylabel("MAE (deg F)", color=INK)
ax.set_title(f"Five-season rolling backtest · {total_pairs:,} forecast/outcome pairs · thin lines are individual seasons",
             color="w", loc="left")
ax.set_xticks([1, 24, 48, 72, 96, 120, 144, 168])
ax.grid(alpha=0.15)
ax.tick_params(colors=INK)
ax.legend(frameon=False, labelcolor=INK, fontsize=10)
fig.tight_layout()
fig.savefig("reports/backtest.png", dpi=150, facecolor=BG)
print(f"\ntotal: {total_pairs:,} verified forecast pairs across {len(results['folds'])} seasons")
print("wrote models/backtest.json and reports/backtest.png")
