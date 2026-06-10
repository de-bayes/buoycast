"""Train the weather-aware forecasters.

Hourly (+3/6/12/24 h): buoy lags + forecast-window weather. The lags-only
lasso is kept as an ablation so the lift from weather covariates is visible.
Daily (D+1 .. D+7): calendar-day model on buoy state + per-day weather.

Validation: untouched test window at the end (21 days hourly, 30 days daily),
walk-forward CV inside the training span picks the production model.
Persistence is always reported. Writes models/*.joblib and models/metrics7.json.
"""

import json

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LassoCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import features7

CF = 1.8


def lasso():
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         LassoCV(n_alphas=20, max_iter=5000, precompute=False,
                                 cv=TimeSeriesSplit(3), n_jobs=-1))


def hgb():
    return HistGradientBoostingRegressor(max_iter=400, learning_rate=0.06, random_state=11)


def mae(a, b):
    return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))


def evaluate(X, y, now, test_rows, zoo, ablate_cols=None):
    ok = y.notna() & now.notna()
    X, y, now = X[ok], y[ok], now[ok]
    split = len(X) - test_rows
    Xtr, ytr, Xte, yte = X.iloc[:split], y.iloc[:split], X.iloc[split:], y.iloc[split:]
    out = {"persistence": {"test_mae_f": round(mae(now.iloc[split:], yte) * CF, 2)}}

    cv = TimeSeriesSplit(4)
    best, best_cv = None, np.inf
    for name, maker in zoo.items():
        cols = [c for c in X.columns if not c.startswith("fut_") and not c.startswith("day")
                and not c.startswith("cum")] if name.endswith("lags_only") else list(X.columns)
        fold = []
        for tr, va in cv.split(Xtr):
            m = maker()
            m.fit(Xtr.iloc[tr][cols], ytr.iloc[tr])
            fold.append(mae(m.predict(Xtr.iloc[va][cols]), ytr.iloc[va]))
        m = maker()
        m.fit(Xtr[cols], ytr)
        t = mae(m.predict(Xte[cols]), yte)
        out[name] = {"cv_mae_f": round(float(np.mean(fold)) * CF, 2), "test_mae_f": round(t * CF, 2)}
        if not name.endswith("lags_only") and np.mean(fold) < best_cv:
            best, best_cv, best_cols = name, np.mean(fold), cols
    out["best"] = best

    final = zoo[best]()
    final.fit(X[best_cols] if best_cols != list(X.columns) else X, y)
    return out, final


buoy = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
wx = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)

metrics = {"hourly": {}, "daily": {}}

print("== hourly, weather-aware ==")
for h in features7.HOURLY_HORIZONS:
    X = features7.build_hourly(buoy, wx, h)
    y = buoy["WTMP"].shift(-h)
    res, model = evaluate(X, y, buoy["WTMP"], 24 * 21,
                          {"lasso_wx": lasso, "hgb_wx": hgb, "lasso_lags_only": lasso})
    joblib.dump(model, f"models/WTMPX_{h}h.joblib")
    metrics["hourly"][f"+{h}h"] = res
    print(f"+{h:>2}h  persist {res['persistence']['test_mae_f']:.2f}F  "
          f"lags-only {res['lasso_lags_only']['test_mae_f']:.2f}F  "
          f"wx-lasso {res['lasso_wx']['test_mae_f']:.2f}F  wx-hgb {res['hgb_wx']['test_mae_f']:.2f}F  "
          f"-> {res['best']}")

print("\n== daily, D+1 .. D+7 ==")
for k in features7.DAILY_HORIZONS:
    X, y = features7.build_daily(buoy, wx, k)
    res, model = evaluate(X, y, X["wtmp_now"], 30, {"lasso_wx": lasso, "hgb_wx": hgb})
    joblib.dump(model, f"models/DAILY_{k}d.joblib")
    metrics["daily"][f"D+{k}"] = res
    print(f"D+{k}  persist {res['persistence']['test_mae_f']:.2f}F  "
          f"wx-lasso {res['lasso_wx']['test_mae_f']:.2f}F  wx-hgb {res['hgb_wx']['test_mae_f']:.2f}F  "
          f"-> {res['best']}")

with open("models/metrics7.json", "w") as fh:
    json.dump(metrics, fh, indent=2)
print("\nsaved models/WTMPX_*.joblib, models/DAILY_*.joblib, models/metrics7.json")
