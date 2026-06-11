"""Decisive multi-season validation for two candidate improvements.

A prior single-window study (models/blend.json, models/offshore.json) flagged two
promising leads. This script puts both through the SAME nine-fold rolling-origin
backtest every production feature is vetted on (backtest.py's fold convention),
under pre-registered decision rules, and writes models/validation.json.

For each of backtest.py's nine folds we fit three MEDIAN models fresh on the
fold's TRAIN and score them anchor-blended (TAU=8, CF=1.8) on the fold's TEST:

  1. hgb_base : HistGradientBoostingRegressor(loss='squared_error', max_iter=250,
                learning_rate=0.08, random_state=11) on the standard 46-feature stack.
  2. rf       : RandomForestRegressor(n_estimators=200, min_samples_leaf=8,
                max_features=0.5, n_jobs=-1, random_state=11) on a random 150k-row
                subsample of the fold's TRAIN.
  3. hgb_off  : same HGB as hgb_base but on the stack augmented with fut_offshore
                and fut_onshore (rolling-h means of max(u,0) / max(-u,0) shifted -h,
                mirroring featuresq.future_generic; built via offshore_study, no
                edit to featuresq.py).

Candidates, scored on each fold TEST (deg F MAE per horizon and overall):
  A. equal_blend = 0.5*hgb_base + 0.5*rf   vs   hgb_base
  B. hgb_off                               vs   hgb_base
Persistence carried as reference.

Pre-registered decision rules (stated against results, NOT bent):
  A promotes if: overall mean MAE gain >= 0.03F  AND  blend wins overall in >= 7
                 of 9 folds  AND  wins the MEAN at +72h and +168h.
  B promotes if: overall mean MAE gain >= 0.015F AND  wins overall in >= 6 of 9 folds.

Does NOT touch production artifacts (models/q_*.joblib, publish.py, train_q.py,
site/) and does not refetch data. Writes models/validation.json.

Runtime: 9 folds x (2 HGB + 1 subsampled RF) is heavy (~60-90 min); expected.
"""

import json
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor

import featuresq
from offshore_study import build_offshore_features

TAU = 8.0
CF = 1.8
RF_SUBSAMPLE = 150_000
RNG = np.random.default_rng(11)

# horizons we report the mean at, plus the decision-rule horizons for A
REPORT_H = [24, 72, 168]


def anchor_blend(pred, persist, hte, tte):
    """Production-style anchor blending (exactly backtest.py / bakeoff_blend):
    delta = (obs_now - pred at h=1) per base time, added to every horizon of that
    base time with decay exp(-(h-1)/TAU)."""
    pred = np.asarray(pred, dtype=float)
    m1 = hte == 1
    delta_by_t = dict(zip(tte[m1].values, persist[m1] - pred[m1]))
    delta = np.array([delta_by_t.get(v, 0.0) for v in tte.values])
    decay = np.exp(-(hte - 1) / TAU)
    return pred + delta * decay


def mae_F(pred, y):
    return float(np.mean(np.abs(pred - y))) * CF


def main():
    print("loading data + building stack ...", flush=True)
    buoy = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
    wx = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)
    X, y, t, h = featuresq.stack(buoy, wx)
    yv = y.to_numpy()

    # offshore augmentation: built once over the full stack (same row order as
    # featuresq.stack), then attached to X's index so fold masks apply identically.
    extra = build_offshore_features(buoy, wx)
    assert len(extra) == len(X), f"offshore row mismatch {len(extra)} vs {len(X)}"
    extra.index = X.index
    Xoff = pd.concat([X, extra], axis=1)
    print(f"stacked rows: {len(X)} · base feats: {X.shape[1]} · "
          f"augmented feats: {Xoff.shape[1]} · horizons: {len(featuresq.HSET)}", flush=True)

    # backtest.py's nine folds, verbatim
    folds = []
    for year in [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]:
        in_year = t[(t.year == year)]
        if len(in_year) == 0:
            continue
        wend = in_year.max()
        folds.append((str(year), wend - pd.Timedelta(days=45), wend))
    folds.append(("2026", t.max() - pd.Timedelta(days=35), t.max()))

    fit_hgb = lambda: HistGradientBoostingRegressor(
        loss="squared_error", max_iter=250, learning_rate=0.08, random_state=11)
    fit_rf = lambda: RandomForestRegressor(
        n_estimators=200, min_samples_leaf=8, max_features=0.5, n_jobs=-1, random_state=11)

    fold_records = []
    for name, wstart, wend in folds:
        tr = t <= (wstart - pd.Timedelta(days=8))
        te = (t >= wstart) & (t <= wend)
        if te.sum() < 1000:
            print(f"fold {name}: too small ({int(te.sum())} test rows), skipped", flush=True)
            continue

        t0 = time.time()
        # tr/te come from comparing a DatetimeIndex, so they are plain numpy
        # bool arrays (same as backtest.py), not pandas Series.
        idx_tr = np.flatnonzero(np.asarray(tr))
        hte, tte = h[te], t[te]
        yte = yv[te]
        persist = X[te]["WTMP"].to_numpy()

        # --- hgb_base on the 46-feature stack ---
        mb = fit_hgb(); mb.fit(X[tr], y[tr])
        pred_base = anchor_blend(mb.predict(X[te]), persist, hte, tte)

        # --- rf on a 150k-row subsample of the fold TRAIN ---
        if len(idx_tr) > RF_SUBSAMPLE:
            sub = RNG.choice(len(idx_tr), size=RF_SUBSAMPLE, replace=False)
            rows = idx_tr[sub]
            rf_note = f"(150k subsample of {len(idx_tr)})"
        else:
            rows = idx_tr
            rf_note = f"({len(idx_tr)} rows)"
        mr = fit_rf(); mr.fit(X.iloc[rows], y.iloc[rows])
        pred_rf = anchor_blend(mr.predict(X[te]), persist, hte, tte)

        # --- hgb_off on the 48-feature augmented stack ---
        mo = fit_hgb(); mo.fit(Xoff[tr], y[tr])
        pred_off = anchor_blend(mo.predict(Xoff[te]), persist, hte, tte)

        # candidate A: equal blend of the two anchor-blended members
        pred_blend = 0.5 * pred_base + 0.5 * pred_rf

        rec = {
            "name": name,
            "window": f"{wstart:%Y-%m-%d} to {wend:%Y-%m-%d}",
            "n": int(te.sum()),
            "train_n": int(tr.sum()),
            "rf_note": rf_note,
            "mae_base": {"overall": round(mae_F(pred_base, yte), 4), "by_h": {}},
            "mae_blend": {"overall": round(mae_F(pred_blend, yte), 4), "by_h": {}},
            "mae_off": {"overall": round(mae_F(pred_off, yte), 4), "by_h": {}},
            "mae_persist": {"overall": round(mae_F(persist, yte), 4), "by_h": {}},
        }
        for hz in REPORT_H:
            m = hte == hz
            if m.sum() < 30:
                for key in ("mae_base", "mae_blend", "mae_off", "mae_persist"):
                    rec[key]["by_h"][str(hz)] = None
                continue
            rec["mae_base"]["by_h"][str(hz)] = round(mae_F(pred_base[m], yte[m]), 4)
            rec["mae_blend"]["by_h"][str(hz)] = round(mae_F(pred_blend[m], yte[m]), 4)
            rec["mae_off"]["by_h"][str(hz)] = round(mae_F(pred_off[m], yte[m]), 4)
            rec["mae_persist"]["by_h"][str(hz)] = round(mae_F(persist[m], yte[m]), 4)
        fold_records.append(rec)

        print(f"fold {name} ({rec['window']}): {rec['n']} pairs · {rf_note} · "
              f"base {rec['mae_base']['overall']:.4f}F  "
              f"blend {rec['mae_blend']['overall']:.4f}F  "
              f"off {rec['mae_off']['overall']:.4f}F  "
              f"persist {rec['mae_persist']['overall']:.4f}F · "
              f"{time.time() - t0:.0f}s", flush=True)

    nf = len(fold_records)

    # --- means across folds (only folds present; horizons only where not None) ---
    def mean_overall(key):
        return round(float(np.mean([r[key]["overall"] for r in fold_records])), 4)

    def mean_h(key, hz):
        vals = [r[key]["by_h"][str(hz)] for r in fold_records if r[key]["by_h"][str(hz)] is not None]
        return round(float(np.mean(vals)), 4) if vals else None

    mean = {}
    for key in ("mae_base", "mae_blend", "mae_off", "mae_persist"):
        mean[key] = {"overall": mean_overall(key),
                     "by_h": {str(hz): mean_h(key, hz) for hz in REPORT_H}}

    # --- candidate A scoring ---
    gain_A_overall = round(mean["mae_base"]["overall"] - mean["mae_blend"]["overall"], 4)
    wins_A = sum(1 for r in fold_records
                 if r["mae_blend"]["overall"] < r["mae_base"]["overall"])
    gain_A_72 = (None if mean["mae_blend"]["by_h"]["72"] is None else
                 round(mean["mae_base"]["by_h"]["72"] - mean["mae_blend"]["by_h"]["72"], 4))
    gain_A_168 = (None if mean["mae_blend"]["by_h"]["168"] is None else
                  round(mean["mae_base"]["by_h"]["168"] - mean["mae_blend"]["by_h"]["168"], 4))
    A_rule_gain = gain_A_overall >= 0.03
    A_rule_folds = wins_A >= 7
    A_rule_72 = gain_A_72 is not None and gain_A_72 > 0
    A_rule_168 = gain_A_168 is not None and gain_A_168 > 0
    A_promote = A_rule_gain and A_rule_folds and A_rule_72 and A_rule_168
    decision_A = (
        f"{'PROMOTE' if A_promote else 'DO NOT PROMOTE'} — "
        f"equal_blend(0.5*hgb_base+0.5*rf) vs hgb_base. "
        f"overall mean MAE gain {gain_A_overall:+.4f}F (need >= 0.03F: {A_rule_gain}); "
        f"blend wins overall in {wins_A}/{nf} folds (need >= 7: {A_rule_folds}); "
        f"mean gain +72h {gain_A_72:+.4f}F (need >0: {A_rule_72}), "
        f"+168h {gain_A_168:+.4f}F (need >0: {A_rule_168})."
    )

    # --- candidate B scoring ---
    gain_B_overall = round(mean["mae_base"]["overall"] - mean["mae_off"]["overall"], 4)
    wins_B = sum(1 for r in fold_records
                 if r["mae_off"]["overall"] < r["mae_base"]["overall"])
    B_rule_gain = gain_B_overall >= 0.015
    B_rule_folds = wins_B >= 6
    B_promote = B_rule_gain and B_rule_folds
    decision_B = (
        f"{'PROMOTE' if B_promote else 'DO NOT PROMOTE'} — "
        f"hgb_off vs hgb_base. "
        f"overall mean MAE gain {gain_B_overall:+.4f}F (need >= 0.015F: {B_rule_gain}); "
        f"off wins overall in {wins_B}/{nf} folds (need >= 6: {B_rule_folds})."
    )

    rules = (
        "A promotes iff overall mean MAE gain >= 0.03F AND blend wins overall in "
        ">= 7 of 9 folds AND wins the mean at +72h AND +168h. "
        "B promotes iff overall mean MAE gain >= 0.015F AND wins overall in >= 6 of 9 "
        "folds. Pre-registered; stated against results, not bent. All models are "
        "anchor-blended median regressors (TAU=8) exactly as production; MAE deg F "
        "(CF=1.8); rf on a 150k-row subsample of each fold's TRAIN; hgb_off adds "
        "fut_offshore/fut_onshore mirroring featuresq.future_generic. Folds replicate "
        "backtest.py (2018-2025 season-end 45-day windows + 2026 last-35-days; TRAIN "
        "ends 8d before each window; folds with <1000 test rows skipped)."
    )

    out = {
        "folds": fold_records,
        "mean": mean,
        "n_folds": nf,
        "candidate_A": {
            "gain_overall_F": gain_A_overall, "wins_overall": wins_A, "of_folds": nf,
            "gain_+72h_F": gain_A_72, "gain_+168h_F": gain_A_168, "promote": A_promote,
        },
        "candidate_B": {
            "gain_overall_F": gain_B_overall, "wins_overall": wins_B, "of_folds": nf,
            "promote": B_promote,
        },
        "decision_A": decision_A,
        "decision_B": decision_B,
        "rules": rules,
    }
    with open("models/validation.json", "w") as fh:
        json.dump(out, fh, indent=2)

    # --- printed report ---
    print("\n" + "=" * 96)
    print(f"MULTI-SEASON VALIDATION — {nf} rolling-origin folds — TEST MAE (deg F)")
    print("=" * 96)
    header = (f"{'fold':6s} {'window':27s} {'pairs':>7s}  "
              f"{'base':>7s} {'blendA':>7s} {'hgb_off':>7s} {'persist':>7s}  "
              f"{'gainA':>7s} {'gainB':>7s}")
    print(header)
    print("-" * len(header))
    for r in fold_records:
        gA = r["mae_base"]["overall"] - r["mae_blend"]["overall"]
        gB = r["mae_base"]["overall"] - r["mae_off"]["overall"]
        print(f"{r['name']:6s} {r['window']:27s} {r['n']:7d}  "
              f"{r['mae_base']['overall']:7.4f} {r['mae_blend']['overall']:7.4f} "
              f"{r['mae_off']['overall']:7.4f} {r['mae_persist']['overall']:7.4f}  "
              f"{gA:+7.4f} {gB:+7.4f}")
    print("-" * len(header))
    print(f"{'MEAN':6s} {'':27s} {'':>7s}  "
          f"{mean['mae_base']['overall']:7.4f} {mean['mae_blend']['overall']:7.4f} "
          f"{mean['mae_off']['overall']:7.4f} {mean['mae_persist']['overall']:7.4f}  "
          f"{gain_A_overall:+7.4f} {gain_B_overall:+7.4f}")

    print("\nMean MAE by horizon (deg F):")
    print(f"  {'h':>4s}  {'base':>8s} {'blendA':>8s} {'hgb_off':>8s} {'persist':>8s}")
    for hz in REPORT_H:
        b = mean["mae_base"]["by_h"][str(hz)]
        bl = mean["mae_blend"]["by_h"][str(hz)]
        of = mean["mae_off"]["by_h"][str(hz)]
        ps = mean["mae_persist"]["by_h"][str(hz)]
        fmt = lambda v: f"{v:8.4f}" if v is not None else f"{'--':>8s}"
        print(f"  {hz:>4d}  {fmt(b)} {fmt(bl)} {fmt(of)} {fmt(ps)}")

    print("\n" + "=" * 96)
    print("PRE-REGISTERED VERDICTS")
    print("=" * 96)
    print("Candidate A (equal_blend of hgb_base + rf):")
    print(f"  overall mean gain {gain_A_overall:+.4f}F  (rule >= 0.03F: {'PASS' if A_rule_gain else 'FAIL'})")
    print(f"  wins overall {wins_A}/{nf}              (rule >= 7: {'PASS' if A_rule_folds else 'FAIL'})")
    print(f"  mean gain +72h {gain_A_72:+.4f}F      (rule >0: {'PASS' if A_rule_72 else 'FAIL'})")
    print(f"  mean gain +168h {gain_A_168:+.4f}F     (rule >0: {'PASS' if A_rule_168 else 'FAIL'})")
    print(f"  => {'PROMOTE' if A_promote else 'DO NOT PROMOTE'}")
    print("\nCandidate B (hgb_off, +fut_offshore/fut_onshore):")
    print(f"  overall mean gain {gain_B_overall:+.4f}F  (rule >= 0.015F: {'PASS' if B_rule_gain else 'FAIL'})")
    print(f"  wins overall {wins_B}/{nf}              (rule >= 6: {'PASS' if B_rule_folds else 'FAIL'})")
    print(f"  => {'PROMOTE' if B_promote else 'DO NOT PROMOTE'}")
    print("\nwrote models/validation.json")


if __name__ == "__main__":
    main()
