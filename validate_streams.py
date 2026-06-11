"""Nine-fold rolling-origin validation of the three new data streams (MUR
satellite SST, LMHOFS physics model, Chicago beach sensors) against the
production 46-feature stack. Same folds, anchor blending, and scoring as
backtest.py / validate_candidates.py.

Variants, each a fresh median HGB per fold:
  base   the production stack
  sat    base + SAT block      phys   base + PHYS block
  beach  base + BEACH block    all    base + every block

Pre-registered rules, stated before results and not bent. A stream is judged
only on folds where it has coverage (>= 60% of test rows carry a non-NaN key
feature; LMHOFS does not exist before 2019-09, judging it on 2018 would be
noise). Promote a variant iff over its covered folds:
  mean MAE gain >= 0.015 F  AND  it wins overall in >= 2/3 of covered folds
  AND no covered fold worsens by more than 0.05 F.
`all` promotes only if it also beats the best single promoted stream.

Writes models/validation_streams.json. Does not touch production artifacts."""

import json
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

import featuresq
import streams

TAU = 8.0
CF = 1.8
REPORT_H = [24, 72, 168]
KEY = {"sat": "sat_x0", "phys": "lmhofs_now", "beach": "beach_ohio"}


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
    assert len(extra) == len(X), f"row mismatch {len(extra)} vs {len(X)}"
    extra.index = X.index

    variants = {"base": X}
    for name, key in [("sat", "SAT"), ("phys", "PHYS"), ("beach", "BEACH")]:
        variants[name] = pd.concat([X, extra[streams.COLS[key]]], axis=1)
    variants["all"] = pd.concat([X, extra], axis=1)
    for name, V in variants.items():
        print(f"  {name}: {V.shape[1]} features", flush=True)

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
            print(f"fold {name}: too small, skipped", flush=True)
            continue
        hte, tte, yte = h[te], t[te], yv[te]
        persist = X[te]["WTMP"].to_numpy()
        rec = {"name": name, "window": f"{wstart:%Y-%m-%d} to {wend:%Y-%m-%d}",
               "n": int(te.sum()), "mae": {}, "by_h": {}, "coverage": {}}
        for vname, key in KEY.items():
            rec["coverage"][vname] = round(
                float(extra.loc[np.asarray(te), key].notna().mean()), 3)
        t0 = time.time()
        for vname, V in variants.items():
            m = fit(); m.fit(V[tr], y[tr])
            pred = anchor_blend(m.predict(V[te]), persist, hte, tte)
            rec["mae"][vname] = round(mae_F(pred, yte), 4)
            rec["by_h"][vname] = {str(hz): round(mae_F(pred[hte == hz], yte[hte == hz]), 4)
                                  for hz in REPORT_H if (hte == hz).sum() >= 30}
        rec["mae"]["persist"] = round(mae_F(persist, yte), 4)
        records.append(rec)
        print(f"fold {name} ({rec['window']}): " +
              "  ".join(f"{k} {v:.4f}" for k, v in rec["mae"].items()) +
              f"  cov {rec['coverage']}  · {time.time() - t0:.0f}s", flush=True)

    # verdicts over covered folds
    verdicts = {}
    for vname in ["sat", "phys", "beach", "all"]:
        if vname == "all":
            cov_folds = [r for r in records
                         if max(r["coverage"].values()) >= 0.6]
        else:
            cov_folds = [r for r in records if r["coverage"][vname] >= 0.6]
        if not cov_folds:
            verdicts[vname] = {"promote": False, "note": "no covered folds"}
            continue
        gains = [r["mae"]["base"] - r["mae"][vname] for r in cov_folds]
        wins = sum(g > 0 for g in gains)
        mean_gain = round(float(np.mean(gains)), 4)
        worst = round(float(min(gains)), 4)
        promote = (mean_gain >= 0.015 and wins >= np.ceil(2 * len(cov_folds) / 3)
                   and worst >= -0.05)
        verdicts[vname] = {
            "covered_folds": [r["name"] for r in cov_folds],
            "mean_gain_F": mean_gain, "wins": int(wins), "of": len(cov_folds),
            "worst_fold_F": worst, "promote": bool(promote)}

    out = {"folds": records, "verdicts": verdicts,
           "rules": ("judge each stream on folds with >=60% test coverage of its key "
                     "feature; promote iff mean gain >=0.015F AND wins >=2/3 of covered "
                     "folds AND no covered fold worsens >0.05F; all must additionally "
                     "beat the best single promoted stream")}
    with open("models/validation_streams.json", "w") as fh:
        json.dump(out, fh, indent=2)

    print("\n" + "=" * 100)
    hdr = f"{'fold':6s} {'pairs':>7s}  " + "".join(f"{k:>8s}" for k in
          ["base", "sat", "phys", "beach", "all", "persist"])
    print(hdr); print("-" * len(hdr))
    for r in records:
        print(f"{r['name']:6s} {r['n']:7d}  " + "".join(
            f"{r['mae'][k]:8.4f}" for k in ["base", "sat", "phys", "beach", "all", "persist"]))
    print("-" * len(hdr))
    means = {k: float(np.mean([r["mae"][k] for r in records]))
             for k in ["base", "sat", "phys", "beach", "all", "persist"]}
    print(f"{'MEAN':6s} {'':7s}  " + "".join(f"{means[k]:8.4f}" for k in means))
    print("\nVERDICTS (covered folds only):")
    for vname, v in verdicts.items():
        if "mean_gain_F" in v:
            print(f"  {vname:6s} gain {v['mean_gain_F']:+.4f}F  wins {v['wins']}/{v['of']}"
                  f"  worst {v['worst_fold_F']:+.4f}F  -> "
                  f"{'PROMOTE' if v['promote'] else 'DO NOT PROMOTE'}")
        else:
            print(f"  {vname:6s} {v['note']}")
    print("\nwrote models/validation_streams.json")


if __name__ == "__main__":
    main()
