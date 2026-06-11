"""Round 2 (FINAL) of the new-stream validation, pre-registered before any
round-2 result was seen. Round 1 (validate_streams.py) promoted nothing, but
phys passed the mean-gain bar (+0.031F over 7 covered folds) while failing on
consistency, and the streams' wins concentrated in bust seasons (2019 fold:
base 1.45F -> all 1.06F). Hypothesis: the absolute-temperature columns
(lmhofs_now, lmhofs_fut, sat_x0, sat_basin, ...) duplicate the buoy state and
add calm-season variance; the orthogonal signal is change and bias.

Lean variants, fresh median HGB per fold, same folds/anchoring/scoring:
  base       the production stack
  phys_lean  base + lmhofs_delta + lmhofs_err
  sat_lean   base + sat_grad_near + sat_grad_far + sat_basin_d3
  both_lean  base + the five columns above

STRICTER round-2 rules (multiplicity tax, stated in advance, not bent):
promote iff over covered folds (>= 60% key-feature coverage):
  mean gain >= 0.02 F  AND  wins in >= 5/7 (phys-covered) or >= 6/9 (sat)
  AND no covered fold worsens by more than 0.05 F.
If nothing passes, the conclusion stands: these streams stay out of the model.

Writes models/validation_streams2.json."""

import json
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

import featuresq
import streams

TAU = 8.0
CF = 1.8
LEAN = {"phys_lean": ["lmhofs_delta", "lmhofs_err"],
        "sat_lean": ["sat_grad_near", "sat_grad_far", "sat_basin_d3"],
        "both_lean": ["lmhofs_delta", "lmhofs_err",
                      "sat_grad_near", "sat_grad_far", "sat_basin_d3"]}
KEY = {"phys_lean": "lmhofs_delta", "sat_lean": "sat_grad_near",
       "both_lean": "sat_grad_near"}
MIN_WINS = {"phys_lean": 5, "sat_lean": 6, "both_lean": 6}


def anchor_blend(pred, persist, hte, tte):
    pred = np.asarray(pred, dtype=float)
    m1 = hte == 1
    delta_by_t = dict(zip(tte[m1].values, persist[m1] - pred[m1]))
    delta = np.array([delta_by_t.get(v, 0.0) for v in tte.values])
    return pred + delta * np.exp(-(hte - 1) / TAU)


mae_F = lambda p, y: float(np.mean(np.abs(p - y))) * CF


def main():
    print("loading data + building stacks ...", flush=True)
    buoy = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
    wx = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)
    X, y, t, h = featuresq.stack(buoy, wx)
    yv = y.to_numpy()
    extra = streams.build_blocks(buoy)
    extra.index = X.index

    variants = {"base": X}
    for name, cols in LEAN.items():
        variants[name] = pd.concat([X, extra[cols]], axis=1)

    folds = []
    for year in [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]:
        in_year = t[(t.year == year)]
        if len(in_year) == 0:
            continue
        wend = in_year.max()
        folds.append((str(year), wend - pd.Timedelta(days=45), wend))
    folds.append(("2026", t.max() - pd.Timedelta(days=35), t.max()))

    fit = lambda: HistGradientBoostingRegressor(
        loss="squared_error", max_iter=250, learning_rate=0.08, random_state=11)

    records = []
    for name, wstart, wend in folds:
        tr = t <= (wstart - pd.Timedelta(days=8))
        te = (t >= wstart) & (t <= wend)
        if te.sum() < 1000:
            continue
        hte, tte, yte = h[te], t[te], yv[te]
        persist = X[te]["WTMP"].to_numpy()
        rec = {"name": name, "n": int(te.sum()), "mae": {}, "coverage": {}}
        for vname, key in KEY.items():
            rec["coverage"][vname] = round(
                float(extra.loc[np.asarray(te), key].notna().mean()), 3)
        t0 = time.time()
        for vname, V in variants.items():
            m = fit(); m.fit(V[tr], y[tr])
            pred = anchor_blend(m.predict(V[te]), persist, hte, tte)
            rec["mae"][vname] = round(mae_F(pred, yte), 4)
        records.append(rec)
        print(f"fold {name}: " + "  ".join(f"{k} {v:.4f}" for k, v in rec["mae"].items())
              + f" · {time.time() - t0:.0f}s", flush=True)

    verdicts = {}
    for vname in LEAN:
        cov = [r for r in records if r["coverage"][vname] >= 0.6]
        gains = [r["mae"]["base"] - r["mae"][vname] for r in cov]
        wins = sum(g > 0 for g in gains)
        verdicts[vname] = {
            "covered": [r["name"] for r in cov],
            "mean_gain_F": round(float(np.mean(gains)), 4),
            "wins": int(wins), "of": len(cov),
            "worst_fold_F": round(float(min(gains)), 4),
            "promote": bool(np.mean(gains) >= 0.02 and wins >= MIN_WINS[vname]
                            and min(gains) >= -0.05)}

    with open("models/validation_streams2.json", "w") as fh:
        json.dump({"folds": records, "verdicts": verdicts}, fh, indent=2)

    print("\nROUND 2 VERDICTS:")
    for vname, v in verdicts.items():
        print(f"  {vname:10s} gain {v['mean_gain_F']:+.4f}F  wins {v['wins']}/{v['of']}"
              f"  worst {v['worst_fold_F']:+.4f}F  -> "
              f"{'PROMOTE' if v['promote'] else 'DO NOT PROMOTE'}")
    print("wrote models/validation_streams2.json")


if __name__ == "__main__":
    main()
