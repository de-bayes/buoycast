"""Publish the live probabilistic forecast for the site: a 168-hour hourly
water-temperature trajectory with P5/P25/P50/P75/P95 bands (anchor-blended
to the current observation), a daily digest, current conditions, and the
full validation statistics. Writes site/data.json and site/stats.json."""

import json
import pathlib
import shutil

import joblib
import numpy as np
import pandas as pd

import buoy
import featuresq
import fetch_weather

TAU = 8.0
F = lambda c: c * 1.8 + 32

MEMBER_LABEL = {"gfs_seamless": "GFS (NOAA)", "ecmwf_ifs025": "ECMWF",
                "icon_seamless": "ICON (DWD)", "gem_seamless": "GEM (Canada)",
                "gfs_blend": "GFS blend"}
WIN = 7  # centered rolling window for display smoothing


def smooth_fade(arr, hs):
    """7-h centered smoothing that fades in by lead so h=1 stays pinned."""
    s = pd.Series(arr).rolling(WIN, min_periods=1, center=True).mean().to_numpy()
    w = np.clip((hs - 1) / 11.0, 0.0, 1.0)
    return arr * (1 - w) + s * w


print("fetching buoy realtime and weather ensemble...")
hourly_buoy = buoy.to_hourly([buoy.fetch_realtime()])
wx_hist = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)

# 31 GEFS perturbed members (sampled weather uncertainty) plus the ECMWF /
# ICON / GEM deterministic runs (model diversity GEFS alone cannot see).
members_wx = {}
try:
    members_wx.update(fetch_weather.gefs_members())
except Exception as e:
    print(f"  GEFS ensemble skipped ({e})")
try:
    det = fetch_weather.member_forecasts(["ecmwf_ifs025", "icon_seamless", "gem_seamless"])
    members_wx.update(det)
except Exception as e:
    print(f"  deterministic members skipped ({e})")
if not members_wx:  # total fallback: the default blended forecast as one member
    members_wx = {"gfs_blend": fetch_weather.frame(fetch_weather.get(
        fetch_weather.FORECAST.format(lat=fetch_weather.LAT, lon=fetch_weather.LON)))}
print(f"ensemble members: {len(members_wx)} ({', '.join(list(members_wx)[:4])}...)")

t0 = hourly_buoy.index[-1]
obs_now = float(hourly_buoy["WTMP"].ffill().iloc[-1])
horizons = list(range(1, 169))
hs = np.array(horizons, dtype=float)
decay = np.exp(-(hs - 1) / TAU)

median_model = joblib.load("models/q_50.joblib")
feat_cols = list(median_model.feature_names_in_)

# run the water-temp model on each weather member (perfect-prog, no anchor yet)
member_names, member_raw, wx_blend = [], [], None
for name, fc in members_wx.items():
    wxm = pd.concat([wx_hist, fc])
    wxm = wxm[~wxm.index.duplicated(keep="last")].sort_index()
    if wx_blend is None:
        wx_blend = wxm  # first member also serves the past-forecast verification trace
    rows = featuresq.inference_rows(hourly_buoy, wxm, t0, horizons).reindex(columns=feat_cols)
    member_raw.append(median_model.predict(rows))
    member_names.append(name)
member_raw = np.vstack(member_raw)  # (K, 168) deg C

# anchor each member individually: the current temperature is measured, not
# uncertain, so every simulated future launches exactly from the observation
# and the spread measures genuine divergence, not initial-condition bias
deltas = obs_now - member_raw[:, 0]
member_anch = member_raw + deltas[:, None] * decay[None, :]
p50 = member_anch.mean(axis=0)
sigma_wx = member_anch.std(axis=0, ddof=1) if member_anch.shape[0] > 1 else np.zeros_like(p50)
member_disp = member_anch

# bands = perfect-weather residual (backtest calibration) (+) weather-model spread,
# combined in quadrature. The two are independent: the backtest residual is
# measured under ERA5 (perfect weather), the ensemble spread is the weather term.
with open("models/qstats.json") as fh:
    calib = json.load(fh)["calib"]
bt_calib_path = pathlib.Path("models/backtest.json")
if bt_calib_path.exists():
    bc = json.load(open(bt_calib_path)).get("calib")
    if bc:
        calib = bc
        print(f"using backtest calibration ({len(calib)} horizons)")
ch = np.array(sorted(int(k) for k in calib))
getc = lambda key: np.interp(hs, ch, [calib[str(k)][key] for k in ch])
# per-member anchoring already pins sigma to ~0 at h=1 and lets it grow with
# lead, so no extra fade factor is needed on the weather term
Z = {"e05": -1.645, "e25": -0.674, "e75": 0.674, "e95": 1.645}
offsets = {}
for key in ["e05", "e25", "e75", "e95"]:
    resid = np.abs(getc(key))                      # perfect-weather half-width (C)
    wxterm = abs(Z[key]) * sigma_wx                 # weather-driven half-width (C)
    mag = np.sqrt(resid ** 2 + wxterm ** 2)
    offsets[key] = np.sign(Z[key]) * np.maximum.accumulate(mag)

mat = np.sort(np.stack([
    smooth_fade(p50 + offsets["e05"], hs), smooth_fade(p50 + offsets["e25"], hs),
    smooth_fade(p50, hs),
    smooth_fade(p50 + offsets["e75"], hs), smooth_fade(p50 + offsets["e95"], hs),
]), axis=0)

trajectory = []
for i, h in enumerate(horizons):
    valid = t0 + pd.Timedelta(hours=h)
    trajectory.append({
        "h": h, "t": valid.isoformat(),
        "p05": round(F(mat[0][i]), 2), "p25": round(F(mat[1][i]), 2),
        "p50": round(F(mat[2][i]), 2), "p75": round(F(mat[3][i]), 2),
        "p95": round(F(mat[4][i]), 2),
    })

daily, byday = [], {}
for pt in trajectory:
    byday.setdefault(pt["t"][:10], []).append(pt)
for date, pts in sorted(byday.items()):
    if len(pts) < 12:
        continue
    daily.append({
        "date": date,
        "label": pd.Timestamp(date).strftime("%a"),
        "p50": round(float(np.mean([p["p50"] for p in pts])), 1),
        "p05": round(float(np.mean([p["p05"] for p in pts])), 1),
        "p95": round(float(np.mean([p["p95"] for p in pts])), 1),
    })

# verification trace: what the +24h forecast said for each recent hour, so
# the chart shows model calls resolving against the observed line. Built via
# the same assemble() the model was trained on, so the feature set matches.
Xpast = featuresq.assemble(hourly_buoy, wx_blend, 24)
Xpast = Xpast.reindex(columns=feat_cols)
bases = [t0 - pd.Timedelta(hours=k) for k in range(72, 23, -1)]
bases = [b for b in bases if b in Xpast.index]
pastfc = []
if bases:
    p50_past = median_model.predict(Xpast.loc[bases])
    for b, v in zip(bases, p50_past):
        off = int((b + pd.Timedelta(hours=24) - t0) / pd.Timedelta(hours=1))
        pastfc.append({"h": off, "f": round(F(v), 2)})

hist_series = hourly_buoy["WTMP"].ffill().tail(49)
history = [{"h": i - (len(hist_series) - 1), "t": ts.isoformat(), "f": round(F(v), 2)}
           for i, (ts, v) in enumerate(hist_series.items()) if pd.notna(v)]

# per-member smoothed trajectories (the spaghetti)
members_out = []
for k, name in enumerate(member_names):
    line = smooth_fade(member_disp[k], hs)
    members_out.append({"model": MEMBER_LABEL.get(name, name),
                        "traj": [round(F(v), 2) for v in line]})

# uncertainty decomposition (90% half-widths, deg F): the irreducible part the
# model carries even under perfect weather, and the part from weather-model
# disagreement. They combine in quadrature to the published band.
resid90 = np.maximum.accumulate((np.abs(getc("e05")) + np.abs(getc("e95"))) / 2)
unc = [{"h": h, "irreducible": round(float(resid90[i]) * 1.8, 2),
        "weather": round(float(1.645 * sigma_wx[i]) * 1.8, 2)}
       for i, h in enumerate(horizons)]

last = hourly_buoy.ffill().iloc[-1]
out = {
    "generated_utc": pd.Timestamp.now("UTC").isoformat(),
    "valid_utc": t0.isoformat(),
    "now": {
        "wtmp_f": round(F(last["WTMP"]), 1), "atmp_f": round(F(last["ATMP"]), 1),
        "wvht_ft": round(last["WVHT"] * 3.28084, 1),
        "wspd_kt": round(last["WSPD"] * 1.943844, 1), "gst_kt": round(last["GST"] * 1.943844, 1),
    },
    "trajectory": trajectory,
    "history": history,
    "pastfc": pastfc,
    "daily": daily[:7],
    "members": members_out,
    "uncertainty": unc,
}

# fold the multi-season backtest and driver study into the site stats so the
# bottom charts can render interactively from data, not static images
with open("models/qstats.json") as fh:
    qs = json.load(fh)
backtest_path = pathlib.Path("models/backtest.json")
if backtest_path.exists():
    qs["backtest"] = json.load(open(backtest_path))
driver_path = pathlib.Path("reports/correlations.json")
if driver_path.exists():
    qs["driver"] = json.load(open(driver_path))
with open("models/qstats.json", "w") as fh:
    json.dump(qs, fh)

pathlib.Path("site/reports").mkdir(parents=True, exist_ok=True)
for png in ["model_comparison.png", "error_analysis.png", "correlations.png", "backtest.png"]:
    src = pathlib.Path("reports") / png
    if src.exists():
        shutil.copy(src, pathlib.Path("site/reports") / png)
shutil.copy("models/qstats.json", "site/stats.json")

with open("site/data.json", "w") as fh:
    json.dump(out, fh)
print(f"now {out['now']['wtmp_f']}F · +24h {trajectory[23]['p50']}F "
      f"[{trajectory[23]['p05']}-{trajectory[23]['p95']}] · "
      f"+168h {trajectory[167]['p50']}F [{trajectory[167]['p05']}-{trajectory[167]['p95']}]")
print("wrote site/data.json, site/stats.json, copied figures")
