"""TASK 1: model bake-off + convex blend ("master model").

Four median regressors (ridge, bayesian ridge, random forest, squared-error
HGB) are each fit on a gap-separated TRAIN split, anchor-blended exactly as
production does, and combined with convex weights learned to minimise VAL MAE.
The blend is then refit on TRAIN+VAL and scored once on a held-out TEST window
against every single member, the equal-weight blend, and persistence.

Time splits by base time t (8-day gaps so no stacked (t,h) row straddles a
boundary; the longest horizon is 168 h ~= 7 days, the gap absorbs it):
    TEST = last 35 days (the 2026 season-to-date; production convention)
    VAL  = the 35 days of in-season data immediately before TEST, +8-day gap
    TRAIN= everything ending 8 days before VAL start

IMPORTANT (seasonal buoy): NDBC 45174 is offline in winter. It went dark
2025-11-04 and returned 2026-05-18, so the literal calendar window "35 days
before TEST" lands entirely in a dead season (0 rows). VAL is therefore anchored
to the last base time that exists before TEST's data begins (the tail of the
2025 season), with an 8-day data gap. The real VAL->TEST gap is the ~200-day
winter outage, which trivially satisfies the no-straddle requirement. This is
the honest split; see split printout.

Does NOT touch production artifacts. Writes models/blend.json.
"""

import json
import time

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import BayesianRidge, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import featuresq

CF = 1.8
TAU = 8.0
RNG = np.random.default_rng(11)
FOREST_SUBSAMPLE = 150_000


def make_splits(t):
    """Gap-separated TRAIN/VAL/TEST masks over base time t. TEST = last 35
    calendar days (production convention). VAL = the 35 days of in-season data
    immediately before TEST's data begins, with an 8-day data gap; because of
    the winter outage this is the tail of the prior season. TRAIN = everything
    8 days before VAL. Returns (tr, va, te, splits_dict)."""
    t_end = t.max()
    test_start = t_end - pd.Timedelta(days=35)
    te = t >= test_start
    te_data_start = t[te].min()
    prior_data_end = t[t < te_data_start].max()      # last in-season base time before TEST
    val_end = prior_data_end - pd.Timedelta(days=8)  # 8-day data gap below TEST season
    val_start = val_end - pd.Timedelta(days=35)
    va = (t >= val_start) & (t <= val_end)
    train_end = val_start - pd.Timedelta(days=8)
    tr = t <= train_end
    assert (tr & va).sum() == 0 and (tr & te).sum() == 0 and (va & te).sum() == 0
    assert va.sum() > 0, "empty VAL window"
    splits = {
        "train_end": f"{train_end:%Y-%m-%d}",
        "val_start": f"{val_start:%Y-%m-%d}",
        "val_end": f"{val_end:%Y-%m-%d}",
        "test_start": f"{test_start:%Y-%m-%d}",
        "test_end": f"{t_end:%Y-%m-%d}",
        "val_test_gap_days": int((te_data_start - val_end).days),
    }
    return tr, va, te, splits


def make_members():
    """Fresh, unfit member estimators."""
    return {
        "ridge": Pipeline([
            ("imp", SimpleImputer(strategy="median")),
            ("sc", StandardScaler()),
            ("m", Ridge(alpha=1.0)),
        ]),
        "bayes": Pipeline([
            ("imp", SimpleImputer(strategy="median")),
            ("sc", StandardScaler()),
            ("m", BayesianRidge()),
        ]),
        "forest": RandomForestRegressor(n_estimators=200, min_samples_leaf=8,
                                        max_features=0.5, n_jobs=-1, random_state=11),
        "hgb": HistGradientBoostingRegressor(loss="squared_error", max_iter=500,
                                             learning_rate=0.07, random_state=11),
    }


def fit_members(X, y, mask):
    """Fit each member on the rows selected by `mask`. Forest fits on a random
    150k-row subsample of those rows for tractability."""
    members = make_members()
    Xtr_full, ytr_full = X[mask], y[mask]
    idx_full = np.flatnonzero(mask.to_numpy() if hasattr(mask, "to_numpy") else mask)
    fit = {}
    for name, est in members.items():
        t0 = time.time()
        if name == "forest" and len(idx_full) > FOREST_SUBSAMPLE:
            sub = RNG.choice(len(idx_full), size=FOREST_SUBSAMPLE, replace=False)
            est.fit(X.iloc[idx_full[sub]], y.iloc[idx_full[sub]])
            note = f"(150k subsample of {len(idx_full)})"
        else:
            est.fit(Xtr_full, ytr_full)
            note = f"({len(idx_full)} rows)"
        fit[name] = est
        print(f"  fit {name:7s} {note}  {time.time() - t0:5.1f}s", flush=True)
    return fit


def anchor_blend(pred, persist, hte, tte):
    """Production-style anchor blending applied to a member's raw predictions.
    delta = (obs_now - pred at h=1) per base time, added to all horizons of
    that base time with decay exp(-(h-1)/TAU)."""
    pred = np.asarray(pred, dtype=float)
    m1 = hte == 1
    delta_by_t = dict(zip(tte[m1].values, persist[m1] - pred[m1]))
    delta = np.array([delta_by_t.get(v, 0.0) for v in tte.values])
    decay = np.exp(-(hte - 1) / TAU)
    return pred + delta * decay


def predict_blended(fit, X, mask, t, h):
    """Predict each member on `mask` rows, anchor-blend, return dict name->array
    plus the aligned y, h, persistence (all numpy)."""
    Xs = X[mask]
    hs = h[mask]
    ts = t[mask]
    persist = Xs["WTMP"].to_numpy()
    out = {}
    for name, est in fit.items():
        raw = est.predict(Xs)
        out[name] = anchor_blend(raw, persist, hs, ts)
    return out, hs, persist


def learn_weights(preds, y):
    """Convex weights w>=0, sum 1, minimising MAE of the weighted blend.
    SLSQP from several simplex starts; keep the best."""
    names = list(preds.keys())
    P = np.column_stack([preds[n] for n in names])  # (rows, members)
    yv = np.asarray(y, dtype=float)
    k = len(names)

    def mae(w):
        return float(np.mean(np.abs(P @ w - yv)))

    cons = ({"type": "eq", "fun": lambda w: np.sum(w) - 1.0},)
    bounds = [(0.0, 1.0)] * k

    starts = [np.full(k, 1.0 / k)]
    for i in range(k):  # each vertex
        v = np.full(k, 0.02)
        v[i] = 1.0 - 0.02 * (k - 1)
        starts.append(v)
    for _ in range(8):  # random interior points
        r = RNG.random(k)
        starts.append(r / r.sum())

    best_w, best_v = None, np.inf
    for w0 in starts:
        res = minimize(mae, w0, method="SLSQP", bounds=bounds, constraints=cons,
                       options={"maxiter": 500, "ftol": 1e-10})
        w = np.clip(res.x, 0, None)
        w = w / w.sum()
        v = mae(w)
        if v < best_v:
            best_v, best_w = v, w
    return dict(zip(names, [float(x) for x in best_w])), best_v


def main():
    print("loading data + building stack ...", flush=True)
    buoy = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
    wx = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)
    X, y, t, h = featuresq.stack(buoy, wx)
    print(f"stacked rows: {len(X)} · features: {X.shape[1]} · horizons: {len(featuresq.HSET)}", flush=True)

    tr, va, te, splits = make_splits(t)
    print(f"TRAIN <= {splits['train_end']} ({tr.sum()})  "
          f"VAL {splits['val_start']}..{splits['val_end']} ({va.sum()})  "
          f"TEST >= {splits['test_start']} ({te.sum()})  "
          f"[VAL->TEST gap {splits['val_test_gap_days']}d, the winter outage]", flush=True)

    # --- members fit on TRAIN, weights learned on VAL ---
    print("\nfitting members on TRAIN ...", flush=True)
    fit_tr = fit_members(X, y, tr)
    print("predicting VAL (anchor-blended) ...", flush=True)
    va_preds, va_h, _ = predict_blended(fit_tr, X, va, t, h)
    yva = y[va].to_numpy()

    val_mae = {n: round(float(np.mean(np.abs(p - yva))) * CF, 4) for n, p in va_preds.items()}
    eq = np.mean(np.column_stack(list(va_preds.values())), axis=1)
    val_mae["equal_blend"] = round(float(np.mean(np.abs(eq - yva))) * CF, 4)

    weights, blend_val_c = learn_weights(va_preds, yva)
    blend_val = np.column_stack([va_preds[n] for n in weights]) @ np.array([weights[n] for n in weights])
    val_mae["learned_blend"] = round(float(np.mean(np.abs(blend_val - yva))) * CF, 4)
    print("\nVAL MAE (deg F):")
    for k_, v_ in val_mae.items():
        print(f"  {k_:14s} {v_:.4f}")
    print("learned weights:", {n: round(w, 4) for n, w in weights.items()})

    # --- refit members on TRAIN+VAL, score TEST ---
    print("\nrefitting members on TRAIN+VAL ...", flush=True)
    trva = tr | va
    fit_trva = fit_members(X, y, trva)
    print("predicting TEST (anchor-blended) ...", flush=True)
    te_preds, te_h, te_persist = predict_blended(fit_trva, X, te, t, h)
    yte = y[te].to_numpy()

    w_arr = np.array([weights[n] for n in weights])
    learned = np.column_stack([te_preds[n] for n in weights]) @ w_arr
    equal = np.mean(np.column_stack(list(te_preds.values())), axis=1)

    # assemble every candidate's TEST predictions for scoring
    cand = dict(te_preds)
    cand["equal_blend"] = equal
    cand["learned_blend"] = learned
    cand["persistence"] = te_persist

    def mae_mask(pred, mask):
        return round(float(np.mean(np.abs(pred[mask] - yte[mask]))) * CF, 4)

    hs_report = [1, 24, 72, 168] + [hz for hz in featuresq.HSET if hz not in (1, 24, 72, 168)]
    hs_report = sorted(set(hs_report))

    test_overall = {n: mae_mask(p, np.ones_like(yte, dtype=bool)) for n, p in cand.items()}
    test_by_h = {}
    for hz in featuresq.HSET:
        m = te_h == hz
        if m.sum() < 30:
            continue
        test_by_h[str(hz)] = {n: mae_mask(p, m) for n, p in cand.items()}

    # --- verdict ---
    members_only = {n: test_overall[n] for n in te_preds}
    best_member = min(members_only, key=members_only.get)
    best_member_mae = members_only[best_member]
    learned_mae = test_overall["learned_blend"]
    gain_overall = best_member_mae - learned_mae

    def gain_at(hz):
        d = test_by_h.get(str(hz))
        if d is None:
            return None
        bm = min((d[n] for n in te_preds))
        return round(bm - d["learned_blend"], 4)

    verdict = {
        "best_single_member": best_member,
        "best_single_overall_maeF": best_member_mae,
        "learned_blend_overall_maeF": learned_mae,
        "gain_overall_F": round(gain_overall, 4),
        "gain_+24h_F": gain_at(24),
        "gain_+72h_F": gain_at(72),
        "gain_+168h_F": gain_at(168),
        "meaningful_threshold_F": 0.02,
        "beats_best_member_overall": bool(gain_overall > 0),
        "meaningful": bool(gain_overall >= 0.02),
    }

    notes = (
        "Median regressors, all anchor-blended (tau=8) exactly as production. "
        "Forest fit on a random 150k-row subsample of TRAIN/TRAIN+VAL for "
        "tractability (note in fit_members). Convex weights learned on VAL "
        "MAE via SLSQP from many simplex starts; weights only, no per-horizon "
        "weights, no stacking. Buoy is seasonal: VAL is the tail of the 2025 "
        "season (in-season data just before the 2026 TEST), the ~200-day winter "
        "outage forms the VAL->TEST gap, so no stacked (t,h) row straddles a "
        "split. MAE in deg F (CF=1.8)."
    )

    out = {
        "weights": weights,
        "val_mae": val_mae,
        "test_overall": test_overall,
        "test_by_h": test_by_h,
        "train_rows": int(tr.sum()),
        "trainval_rows": int(trva.sum()),
        "val_rows": int(va.sum()),
        "test_rows": int(te.sum()),
        "splits": splits,
        "verdict": verdict,
        "notes": notes,
    }
    with open("models/blend.json", "w") as fh:
        json.dump(out, fh, indent=2)

    # --- printed report ---
    print("\n" + "=" * 78)
    print("TASK 1 RESULTS — TEST MAE (deg F)")
    print("=" * 78)
    cols = [1, 24, 72, 168]
    order = list(te_preds) + ["equal_blend", "learned_blend", "persistence"]
    header = f"{'model':16s}" + "".join(f"  +{c:>4}h" for c in cols) + f"  {'overall':>8}"
    print(header)
    print("-" * len(header))
    for n in order:
        row = f"{n:16s}"
        for c in cols:
            v = test_by_h.get(str(c), {}).get(n)
            row += f"  {v:6.3f}" if v is not None else f"  {'--':>6}"
        row += f"  {test_overall[n]:8.4f}"
        print(row)
    print("-" * len(header))
    print(f"\nlearned weights: " + ", ".join(f"{n}={w:.3f}" for n, w in weights.items()))
    print(f"best single member: {best_member} ({best_member_mae:.4f}F)")
    print(f"learned blend overall: {learned_mae:.4f}F  "
          f"(gain over best member: {gain_overall:+.4f}F)")
    print(f"gain at +24h: {verdict['gain_+24h_F']:+}F · "
          f"+72h: {verdict['gain_+72h_F']:+}F · +168h: {verdict['gain_+168h_F']:+}F")
    if verdict["meaningful"]:
        print(f"VERDICT: learned blend beats best member by >= 0.02F overall — meaningful.")
    elif verdict["beats_best_member_overall"]:
        print(f"VERDICT: learned blend wins overall but by < 0.02F — within noise, "
              f"not worth the 4x inference cost.")
    else:
        print(f"VERDICT: learned blend does NOT beat the best single member overall.")
    print("wrote models/blend.json")


if __name__ == "__main__":
    main()
