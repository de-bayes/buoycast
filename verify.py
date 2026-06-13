"""Live verification: score the forecasts we actually published against what the
lake actually did, and write site/verify.json for the Track Record page.

Honest by construction. publish.py appends every forecast it ships to
data/fc_log.jsonl; here we join each logged quantile forecast to the observed
water temperature at its valid time as soon as it resolves, then aggregate a
rolling 30-day skill-by-lead, band coverage (claimed vs observed), bias, and
skill over persistence. The log records the real published numbers, so this
captures weather-forecast error too, not just the model's perfect-prog error.

Entries tagged origin "hindcast" are a one-time reconstruction (seed_verify.py)
so the page is not empty on day one; "live" entries are genuine published
forecasts and supersede the seed as they accumulate. The page labels both.
"""

import json
import pathlib

import numpy as np
import pandas as pd

LOG_PATH = pathlib.Path("data/fc_log.jsonl")
LEADS = [6, 12, 24, 48, 72, 120, 168]   # leads we log and score (hours)
KEEP_DAYS = 45                          # prune the log to this many days
WINDOW_DAYS = 30                        # rolling window for the headline skill
F = lambda c: c * 1.8 + 32


def fc_from_trajectory(trajectory, leads=LEADS):
    """Pull the per-lead quantile dict the log stores from publish.py's full
    168-row trajectory (1-indexed by lead, deg F)."""
    return {str(h): {k: trajectory[h - 1][k] for k in ("p05", "p25", "p50", "p75", "p95")}
            for h in leads}


def append(t0, fc_by_lead, obs_now_f, generated_utc, origin="live"):
    """Append one published forecast to the log (deduping on valid base time +
    origin, keeping the latest), then prune to KEEP_DAYS. fc_by_lead maps str(h)
    -> {p05,p25,p50,p75,p95} in deg F."""
    rec = {"valid": t0.isoformat(), "gen": generated_utc, "origin": origin,
           "obs_now_f": round(float(obs_now_f), 2), "fc": fc_by_lead}
    rows = _read()
    rows = [r for r in rows if r.get("valid") != rec["valid"] or r.get("origin") != origin]
    rows.append(rec)
    cutoff = pd.Timestamp(t0).tz_convert("UTC") - pd.Timedelta(days=KEEP_DAYS)
    rows = [r for r in rows if pd.Timestamp(r["valid"]) >= cutoff]
    rows.sort(key=lambda r: r["valid"])
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _read():
    if not LOG_PATH.exists():
        return []
    out = []
    for line in LOG_PATH.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def build(obs_wtmp_c, now, backtest_path="models/backtest.json", band_scale=None):
    """Score the log against observed water temp (a pandas Series in deg C,
    hourly-indexed UTC) as of `now`. Returns the verify.json dict."""
    obs = (obs_wtmp_c.astype(float) * 1.8 + 32).dropna()
    obs = obs[~obs.index.duplicated(keep="last")]
    obs_lookup = obs.to_dict()
    rows = _read()

    # explode log -> one scored record per (forecast base, lead) that has resolved
    pts = []
    for r in rows:
        base = pd.Timestamp(r["valid"])
        for h_str, q in r["fc"].items():
            h = int(h_str)
            vt = base + pd.Timedelta(hours=h)
            if vt > now:
                continue
            actual = obs_lookup.get(vt)
            if actual is None:
                continue
            pts.append({"base": base, "h": h, "vt": vt, "actual": float(actual),
                        "p05": q["p05"], "p25": q["p25"], "p50": q["p50"],
                        "p75": q["p75"], "p95": q["p95"],
                        "persist": r["obs_now_f"], "origin": r.get("origin", "live")})

    win_start = now - pd.Timedelta(days=WINDOW_DAYS)
    win = [p for p in pts if p["base"] >= win_start]

    def agg(group):
        if not group:
            return None
        err = np.array([p["p50"] - p["actual"] for p in group])
        perr = np.array([p["persist"] - p["actual"] for p in group])
        c90 = np.mean([p["p05"] <= p["actual"] <= p["p95"] for p in group])
        c50 = np.mean([p["p25"] <= p["actual"] <= p["p75"] for p in group])
        return {"n": len(group), "mae_f": round(float(np.mean(np.abs(err))), 3),
                "mae_persist_f": round(float(np.mean(np.abs(perr))), 3),
                "cover90": round(float(c90), 3), "cover50": round(float(c50), 3),
                "bias_f": round(float(np.mean(err)), 3)}

    by_lead = []
    for h in LEADS:
        a = agg([p for p in win if p["h"] == h])
        if a:
            a["h"] = h
            by_lead.append(a)

    # recent +24h forecast vs actual, chronological, last 14 days, for the chart
    recent = sorted([p for p in pts if p["h"] == 24 and p["base"] >= now - pd.Timedelta(days=14)],
                    key=lambda p: p["vt"])
    recent24 = [{"valid": p["vt"].isoformat(), "p05": p["p05"], "p50": p["p50"],
                 "p95": p["p95"], "actual": round(p["actual"], 2), "origin": p["origin"]}
                for p in recent]

    head_pts = [p for p in win if p["h"] == 24]
    headline = agg(head_pts) or {}
    if headline:
        headline["lead_h"] = 24
        mp = headline["mae_persist_f"]
        headline["skill_pct"] = round((1 - headline["mae_f"] / mp) * 100) if mp else None

    bases = [p["base"] for p in pts]
    out = {
        "generated_utc": now.isoformat(),
        "tracking_since": min(bases).isoformat() if bases else None,
        "n_forecasts": len({p["base"] for p in pts}),
        "n_live": len({p["base"] for p in pts if p["origin"] == "live"}),
        "n_hindcast": len({p["base"] for p in pts if p["origin"] == "hindcast"}),
        "window_days": WINDOW_DAYS,
        "headline": headline,
        "by_lead": by_lead,
        "recent24": recent24,
        "band_scale": band_scale,
    }

    bt_path = pathlib.Path(backtest_path)
    if bt_path.exists():
        bt = json.loads(bt_path.read_text())
        cd = bt.get("cover_diag", {})
        sd = lambda k: float(np.std([f[k] for f in cd.get("by_fold", [])])) if cd.get("by_fold") else None
        out["backtest"] = {
            "leads": bt.get("horizons"),
            "mae_f": bt.get("mean_mae"),
            "mae_persist_f": bt.get("mean_mae_persist"),
            "total_pairs": bt.get("total_pairs"),
            "n_folds": len(bt.get("folds", [])),
            "cover90_spread_static": round(sd("cover90_static"), 3) if sd("cover90_static") else None,
            "cover90_spread_adaptive": round(sd("cover90_adaptive"), 3) if sd("cover90_adaptive") else None,
        }
    return out
