"""Model bake-off for water-temperature forecasting at +3/6/12/24 h.

Validation design:
- The final three in-season weeks are an untouched TEST set.
- Within the remaining TRAIN data, 3-fold walk-forward CV (TimeSeriesSplit)
  ranks models without ever training on the future.
- Persistence (forecast = current value) is scored alongside as the baseline.

The best model per horizon (by CV MAE) is refit on all training data and
saved to models/WTMP_{h}h.joblib, which forecast.py picks up unchanged.
Results land in models/comparison.json and a chart in reports/.
"""

import json

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LassoCV, RidgeCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import features

TEST_HOURS = 24 * 21
ALPHAS = np.logspace(-2, 3, 12)


def zoo():
    impute = SimpleImputer(strategy="median")
    return {
        "ridge": make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), RidgeCV(alphas=ALPHAS)),
        "lasso": make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                               LassoCV(n_alphas=30, max_iter=5000, n_jobs=-1, precompute=False)),
        "knn": make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                             KNeighborsRegressor(n_neighbors=15, weights="distance")),
        "random_forest": make_pipeline(impute, RandomForestRegressor(
            n_estimators=200, min_samples_leaf=3, n_jobs=-1, random_state=11)),
        "extra_trees": make_pipeline(SimpleImputer(strategy="median"), ExtraTreesRegressor(
            n_estimators=200, min_samples_leaf=3, n_jobs=-1, random_state=11)),
        "hist_gb": HistGradientBoostingRegressor(max_iter=400, learning_rate=0.06, random_state=11),
    }


def mae(a, b):
    return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))


df = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
X_all = features.build(df)

results = {}
for h in features.HORIZONS:
    y = df["WTMP"].shift(-h)
    ok = y.notna() & df["WTMP"].notna()
    X, yv, now = X_all[ok], y[ok], df.loc[ok, "WTMP"]

    split = len(X) - TEST_HOURS
    Xtr, ytr = X.iloc[:split], yv.iloc[:split]
    Xte, yte, now_te = X.iloc[split:], yv.iloc[split:], now.iloc[split:]

    print(f"\n=== WTMP +{h}h · train {len(Xtr)} rows, test {len(Xte)} ===")
    horizon = {"persistence": {"cv_mae": None, "test_mae": round(mae(now_te, yte), 3)}}
    print(f"{'persistence':>14}  cv --     test {horizon['persistence']['test_mae']:.3f}")

    cv = TimeSeriesSplit(n_splits=3)
    for name, model in zoo().items():
        fold_maes = []
        for tr_idx, va_idx in cv.split(Xtr):
            model.fit(Xtr.iloc[tr_idx], ytr.iloc[tr_idx])
            fold_maes.append(mae(model.predict(Xtr.iloc[va_idx]), ytr.iloc[va_idx]))
        model.fit(Xtr, ytr)
        test_mae = mae(model.predict(Xte), yte)
        horizon[name] = {"cv_mae": round(float(np.mean(fold_maes)), 3), "test_mae": round(test_mae, 3)}
        print(f"{name:>14}  cv {np.mean(fold_maes):.3f}  test {test_mae:.3f}")

    best = min((k for k in horizon if k != "persistence"), key=lambda k: horizon[k]["cv_mae"])
    horizon["best_by_cv"] = best
    results[f"+{h}h"] = horizon

    winner = zoo()[best]
    winner.fit(Xtr, ytr)
    joblib.dump(winner, f"models/WTMP_{h}h.joblib")
    print(f"  -> best by CV: {best} (saved as production model)")

with open("models/comparison.json", "w") as fh:
    json.dump(results, fh, indent=2)

# keep forecast.py's metrics in sync with the newly chosen production models
with open("models/metrics.json") as fh:
    metrics = json.load(fh)
for h in features.HORIZONS:
    win = results[f"+{h}h"]
    best = win["best_by_cv"]
    metrics[f"WTMP+{h}h"] = {
        "model": best,
        "mae": win[best]["test_mae"],
        "mae_persistence": win["persistence"]["test_mae"],
        "skill_vs_persistence": round(1 - win[best]["test_mae"] / win["persistence"]["test_mae"], 3),
    }
with open("models/metrics.json", "w") as fh:
    json.dump(metrics, fh, indent=2)

# chart: test MAE by horizon, one line per model
import pathlib
pathlib.Path("reports").mkdir(exist_ok=True)
fig, ax = plt.subplots(figsize=(8, 5))
names = ["persistence"] + list(zoo().keys())
for name in names:
    ys = [results[f"+{h}h"][name]["test_mae"] for h in features.HORIZONS]
    ax.plot(features.HORIZONS, ys, marker="o", lw=2 if name != "persistence" else 1.4,
            ls="-" if name != "persistence" else "--", label=name)
ax.set_xlabel("forecast horizon (hours)")
ax.set_ylabel("test MAE (deg C)")
ax.set_title("Wilmette buoy water temp: model comparison on held-out test weeks")
ax.set_xticks(features.HORIZONS)
ax.grid(alpha=0.25)
ax.legend(frameon=False, fontsize=9)
fig.tight_layout()
fig.savefig("reports/model_comparison.png", dpi=150)
print("\nsaved models/comparison.json and reports/model_comparison.png")
