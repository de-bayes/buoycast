"""Train gradient-boosted forecasters for water temperature and wave height
at +3/6/12/24 h, holding out the most recent in-season weeks, and report MAE
against the persistence baseline (forecast = current value). Models are only
worth shipping where they beat persistence; the report makes that visible."""

import json

import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

import features

HOLDOUT_HOURS = 24 * 21  # last three in-season weeks

df = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
X = features.build(df)

metrics = {}
for target in features.TARGETS:
    for h in features.HORIZONS:
        y = df[target].shift(-h)
        ok = y.notna() & df[target].notna()
        Xv, yv, now = X[ok], y[ok], df.loc[ok, target]

        split = len(Xv) - HOLDOUT_HOURS
        model = HistGradientBoostingRegressor(
            max_iter=400, learning_rate=0.06, max_depth=None, random_state=11
        )
        model.fit(Xv.iloc[:split], yv.iloc[:split])

        pred = model.predict(Xv.iloc[split:])
        mae = float((pd.Series(pred, index=yv.index[split:]) - yv.iloc[split:]).abs().mean())
        mae_persist = float((now.iloc[split:] - yv.iloc[split:]).abs().mean())

        joblib.dump(model, f"models/{target}_{h}h.joblib")
        metrics[f"{target}+{h}h"] = {
            "mae": round(mae, 3),
            "mae_persistence": round(mae_persist, 3),
            "skill_vs_persistence": round(1 - mae / mae_persist, 3) if mae_persist else None,
            "train_rows": split,
            "holdout_rows": int(len(Xv) - split),
        }
        beat = "BEATS" if mae < mae_persist else "loses to"
        print(f"{target}+{h:>2}h  mae {mae:.3f}  persistence {mae_persist:.3f}  ({beat} baseline)")

with open("models/metrics.json", "w") as fh:
    json.dump(metrics, fh, indent=2)
print("saved models/ and models/metrics.json")
