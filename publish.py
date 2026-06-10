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

print("fetching buoy realtime and weather forecast...")
hourly_buoy = buoy.to_hourly([buoy.fetch_realtime()])
wx_fc = fetch_weather.frame(fetch_weather.get(
    fetch_weather.FORECAST.format(lat=fetch_weather.LAT, lon=fetch_weather.LON)))
wx_hist = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)
wx = pd.concat([wx_hist, wx_fc])
wx = wx[~wx.index.duplicated(keep="last")].sort_index()

t0 = hourly_buoy.index[-1]
obs_now = float(hourly_buoy["WTMP"].ffill().iloc[-1])
horizons = list(range(1, 169))
rows = featuresq.inference_rows(hourly_buoy, wx, t0, horizons)

models = {q: joblib.load(f"models/q_{int(q * 100):02d}.joblib") for q in featuresq.QUANTILES}
raw = {q: models[q].predict(rows) for q in featuresq.QUANTILES}

# anchor blend the median
hs = np.array(horizons, dtype=float)
delta = obs_now - raw[0.5][0]
decay = np.exp(-(hs - 1) / TAU)
p50 = raw[0.5] + delta * decay

# calibrated bands: offsets from the median follow the empirical residual
# quantiles measured on test per horizon (so they start tight and widen),
# scaled by how wide the model thinks THIS situation is vs the test average,
# and forced to widen monotonically with lead
with open("models/qstats.json") as fh:
    calib = json.load(fh)["calib"]
ch = np.array(sorted(int(k) for k in calib))
get = lambda key: np.interp(hs, ch, [calib[str(k)][key] for k in ch])
band_now = raw[0.95] - raw[0.05]
ratio = np.clip(band_now / np.maximum(get("band90_mean_c"), 0.1), 0.6, 1.6)
offsets = {}
for key, sign in [("e05", -1), ("e25", -1), ("e75", 1), ("e95", 1)]:
    mag = np.abs(get(key)) * ratio
    offsets[key] = sign * np.maximum.accumulate(mag)
mat = np.sort(np.stack([
    p50 + offsets["e05"], p50 + offsets["e25"], p50,
    p50 + offsets["e75"], p50 + offsets["e95"],
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

hist_series = hourly_buoy["WTMP"].ffill().tail(49)
history = [{"h": i - (len(hist_series) - 1), "t": ts.isoformat(), "f": round(F(v), 2)}
           for i, (ts, v) in enumerate(hist_series.items()) if pd.notna(v)]

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
    "daily": daily[:7],
}

# fold the five-season backtest into the site stats when it exists
backtest_path = pathlib.Path("models/backtest.json")
if backtest_path.exists():
    with open(backtest_path) as fh:
        bt = json.load(fh)
    with open("models/qstats.json") as fh:
        qs = json.load(fh)
    qs["backtest"] = bt
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
