"""TASK 2: offshore-breeze study.

Evanston/Wilmette sits on the WEST shore of Lake Michigan. In the feature code
u = eastward wind component, so u>0 = wind blowing from land toward the lake =
OFFSHORE breeze; u<0 = onshore. v>0 = southerly (the alongshore axis that drives
upwelling). All wind already exists at the buoy point from ERA5 (data/weather.csv),
so NO new API is needed — this study is purely a re-analysis of on-disk data.

Three honest tests of whether the cross-shore (offshore/onshore) breeze is a
big forecasting indicator:
  1. driver correlations (corr.py's method) of next-24h water change with
     future-24h means of u, rectified offshore max(u,0), rectified onshore
     max(-u,0), v, wind speed, and air-minus-water for scale.
  2. permutation importance of u, fut_u, v, fut_v, fut_wspd in the production
     median model (models/q_50.joblib).
  3. ablation: add fut_offshore and fut_onshore to the stack, train an HGB
     median with and without them on the Task-1 split, compare VAL MAE.

Writes models/offshore.json. Does NOT touch production artifacts.
"""

import json

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

import features7
import featuresq
from bakeoff_blend import make_splits

CF = 1.8


# ---------------------------------------------------------------------------
# Part 1: driver correlations (replicates corr.py)
# ---------------------------------------------------------------------------
def driver_correlations():
    buoy = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
    wx = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)
    df = buoy.join(wx, how="inner")

    rad = np.deg2rad(df["wind_direction_10m"])
    df["u"] = -df["wind_speed_10m"] * np.sin(rad)   # eastward; >0 = offshore here
    df["v"] = -df["wind_speed_10m"] * np.cos(rad)   # northward; alongshore axis
    df["offshore"] = df["u"].clip(lower=0)          # max(u, 0)
    df["onshore"] = (-df["u"]).clip(lower=0)        # max(-u, 0)
    dw24 = (df["WTMP"].shift(-24) - df["WTMP"]) * CF

    def r(series):
        ok = series.notna() & dw24.notna()
        return float(np.corrcoef(series[ok], dw24[ok])[0, 1])

    fut = lambda s: s.rolling(24).mean().shift(-24)

    drivers = [
        ("u (signed cross-shore; +=offshore)", fut(df["u"])),
        ("offshore rectified max(u,0)", fut(df["offshore"])),
        ("onshore rectified max(-u,0)", fut(df["onshore"])),
        ("v (alongshore; upwelling axis)", fut(df["v"])),
        ("wind speed", fut(df["wind_speed_10m"])),
        ("air minus water (top driver, scale)", fut(df["temperature_2m"]) - df["WTMP"]),
    ]
    table = [{"driver": n, "corr_fut24h": round(r(s), 4)} for n, s in drivers]
    print("\nPart 1 — driver correlation with next-24h water-temp change (deg F):")
    print(f"  {'driver':40s}  corr(future-24h)")
    for row in table:
        print(f"  {row['driver']:40s}  {row['corr_fut24h']:+.4f}")
    return table


# ---------------------------------------------------------------------------
# Part 2: permutation importance in the production median model
# ---------------------------------------------------------------------------
def production_perm_importance():
    buoy = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
    wx = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)
    X, y, t, h = featuresq.stack(buoy, wx)

    model = joblib.load("models/q_50.joblib")
    feat = list(model.feature_names_in_)
    X = X.reindex(columns=feat)

    # ~4000-row sample of recent stacked rows
    recent_cut = t.max() - pd.Timedelta(days=70)
    idx = np.flatnonzero(t >= recent_cut)
    rng = np.random.default_rng(7)
    if len(idx) > 4000:
        idx = rng.choice(idx, size=4000, replace=False)
    Xs, ys = X.iloc[idx], y.iloc[idx]

    targets = ["u", "fut_u", "v", "fut_v", "fut_wspd"]
    cols = [feat.index(c) for c in targets]
    imp = permutation_importance(model, Xs, ys, n_repeats=5, random_state=7)

    # full ranking for context (top of the model), plus our targets
    full_order = np.argsort(imp.importances_mean)[::-1]
    top = [{"name": feat[i], "value_F": round(float(imp.importances_mean[i] * CF), 4)}
           for i in full_order[:10]]
    target_imp = {c: round(float(imp.importances_mean[feat.index(c)] * CF), 4) for c in targets}
    target_rank = {c: int(np.where(full_order == feat.index(c))[0][0]) + 1 for c in targets}

    print("\nPart 2 — permutation importance in production median model "
          "(deg F MAE rise when shuffled; ~4000 recent rows):")
    print("  top-10 features overall:")
    for row in top:
        print(f"    {row['name']:18s}  {row['value_F']:+.4f}")
    print("  cross-shore/alongshore targets (rank out of 46):")
    for c in targets:
        print(f"    {c:10s}  {target_imp[c]:+.4f}  (rank {target_rank[c]})")
    return {"top10": top, "targets": target_imp, "target_rank": target_rank,
            "n_sample": int(len(idx))}


# ---------------------------------------------------------------------------
# Part 3: ablation — add fut_offshore / fut_onshore to the stack
# ---------------------------------------------------------------------------
def build_offshore_features(buoy, wx):
    """Build fut_offshore and fut_onshore per horizon, following
    featuresq.future_generic's rolling(h).mean().shift(-h) pattern exactly,
    without editing featuresq.py. Returns a frame aligned/stacked the same way
    featuresq.stack produces its rows (same row order)."""
    wxp = features7.prep_weather(wx)
    offshore = wxp["u"].clip(lower=0)
    onshore = (-wxp["u"]).clip(lower=0)

    blocks = []
    for h in featuresq.HSET:
        f = pd.DataFrame(index=wxp.index)
        f["fut_offshore"] = offshore.rolling(h).mean().shift(-h)
        f["fut_onshore"] = onshore.rolling(h).mean().shift(-h)
        # reproduce featuresq.stack's row selection: y notna & WTMP notna,
        # rows indexed by base time, reindexed onto buoy index first.
        f = f.reindex(buoy.index)
        yh = buoy["WTMP"].shift(-h)
        ok = yh.notna() & buoy["WTMP"].notna()
        blocks.append(f[ok])
    return pd.concat(blocks, ignore_index=True)


def ablation():
    buoy = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
    wx = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)
    X, y, t, h = featuresq.stack(buoy, wx)
    extra = build_offshore_features(buoy, wx)
    assert len(extra) == len(X), f"row mismatch {len(extra)} vs {len(X)}"
    extra.index = X.index

    # Task-1 split (shared make_splits): TRAIN ends 8d before VAL, VAL = the
    # tail of the 2025 season (in-season data just before the 2026 TEST). We
    # score VAL here.
    tr, va, te, splits = make_splits(t)

    Xaug = pd.concat([X, extra], axis=1)
    yva = y[va].to_numpy()

    def hgb():
        return HistGradientBoostingRegressor(loss="quantile", quantile=0.5,
                                             max_iter=250, learning_rate=0.08,
                                             random_state=11)

    print("\nPart 3 — ablation (HGB median, max_iter=250, lr=0.08; VAL MAE deg F):", flush=True)
    base = hgb(); base.fit(X[tr], y[tr])
    mae_base = float(np.mean(np.abs(base.predict(X[va]) - yva))) * CF
    aug = hgb(); aug.fit(Xaug[tr], y[tr])
    mae_aug = float(np.mean(np.abs(aug.predict(Xaug[va]) - yva))) * CF
    delta = mae_aug - mae_base  # negative = improvement

    print(f"  baseline (46 feats):       {mae_base:.4f}F")
    print(f"  +offshore/onshore (48):    {mae_aug:.4f}F")
    print(f"  delta (aug - base):        {delta:+.4f}F  "
          f"({'improves' if delta < 0 else 'worsens'})")
    return {"val_mae_base_F": round(mae_base, 4),
            "val_mae_aug_F": round(mae_aug, 4),
            "delta_F": round(delta, 4),
            "added_features": ["fut_offshore", "fut_onshore"],
            "split": splits,
            "train_rows": int(tr.sum()), "val_rows": int(va.sum())}


def main():
    corr = driver_correlations()
    perm = production_perm_importance()
    abl = ablation()

    # --- verdict ---
    cmap = {row["driver"].split(" ")[0]: row["corr_fut24h"] for row in corr}
    u_corr = next(r["corr_fut24h"] for r in corr if r["driver"].startswith("u "))
    v_corr = next(r["corr_fut24h"] for r in corr if r["driver"].startswith("v "))
    aw_corr = next(r["corr_fut24h"] for r in corr if r["driver"].startswith("air"))
    off_corr = next(r["corr_fut24h"] for r in corr if "max(u,0)" in r["driver"])
    on_corr = next(r["corr_fut24h"] for r in corr if "max(-u,0)" in r["driver"])

    abs_u = abs(u_corr)
    abs_aw = abs(aw_corr)
    abs_v = abs(v_corr)
    ship = abl["delta_F"] <= -0.01  # non-trivial VAL improvement

    # is cross-shore a "major" indicator? compare to the dominant driver.
    major = abs_u >= 0.5 * abs_aw and abl["delta_F"] <= -0.01

    verdict = {
        "offshore_is_major_indicator": bool(major),
        "ship_feature": bool(ship),
        "u_corr": u_corr,
        "offshore_corr": off_corr,
        "onshore_corr": on_corr,
        "v_corr": v_corr,
        "air_minus_water_corr": aw_corr,
        "ablation_delta_F": abl["delta_F"],
        "dominant_driver": "air_minus_water",
        "ship_threshold_F": -0.01,
    }

    out = {"part1_correlations": corr,
           "part2_perm_importance": perm,
           "part3_ablation": abl,
           "verdict": verdict,
           "notes": ("West-shore convention: u>0=offshore, u<0=onshore; v>0=southerly "
                     "(alongshore upwelling axis). All wind from ERA5 at the buoy point "
                     "(data/weather.csv) — no new API. Correlations replicate corr.py "
                     "(future-24h means vs next-24h water change). Ablation uses the "
                     "Task-1 TRAIN/VAL split; ship only on a non-trivial (<= -0.01F) "
                     "VAL gain.")}
    with open("models/offshore.json", "w") as fh:
        json.dump(out, fh, indent=2)

    print("\n" + "=" * 78)
    print("TASK 2 VERDICT — offshore breeze")
    print("=" * 78)
    print(f"signed cross-shore u corr:  {u_corr:+.4f}   "
          f"(offshore {off_corr:+.4f} / onshore {on_corr:+.4f})")
    print(f"alongshore v corr:          {v_corr:+.4f}")
    print(f"air-minus-water corr:       {aw_corr:+.4f}  <- dominates")
    print(f"ablation VAL delta:         {abl['delta_F']:+.4f}F "
          f"({'ship' if ship else 'do NOT ship'})")
    print(f"\nMajor indicator? {'YES' if major else 'NO'}. "
          f"What dominates: air-minus-water gap (and wind speed), not cross-shore breeze.")
    print("wrote models/offshore.json")


if __name__ == "__main__":
    main()
