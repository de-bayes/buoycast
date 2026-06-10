"""Run the full live forecast and publish site/data.json for the dashboard:
current conditions, weather-aware hourly forecasts (+3/6/12/24 h), the
7-day daily forecast with error bands, and the skill tables. Also copies
the analysis figures into site/reports/."""

import json
import pathlib
import shutil

import joblib
import pandas as pd

import buoy
import features7
import fetch_weather

F = lambda c: round(c * 1.8 + 32, 1)

print("fetching buoy realtime and weather forecast...")
hourly_buoy = buoy.to_hourly([buoy.fetch_realtime()])
wx_fc = fetch_weather.frame(fetch_weather.get(
    fetch_weather.FORECAST.format(lat=fetch_weather.LAT, lon=fetch_weather.LON)))
wx_hist = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)
wx = pd.concat([wx_hist, wx_fc])
wx = wx[~wx.index.duplicated(keep="last")].sort_index()

with open("models/metrics7.json") as fh:
    metrics = json.load(fh)

t0 = hourly_buoy.index[-1]
last = hourly_buoy.ffill().iloc[-1]
out = {
    "generated_utc": pd.Timestamp.now("UTC").isoformat(),
    "valid_utc": t0.isoformat(),
    "now": {
        "wtmp_f": F(last["WTMP"]), "atmp_f": F(last["ATMP"]),
        "wvht_ft": round(last["WVHT"] * 3.28084, 1),
        "wspd_kt": round(last["WSPD"] * 1.943844, 1), "gst_kt": round(last["GST"] * 1.943844, 1),
    },
    "hourly": [], "daily": [], "metrics": metrics,
}

for h in features7.HOURLY_HORIZONS:
    X = features7.build_hourly(hourly_buoy, wx, h)
    model = joblib.load(f"models/WTMPX_{h}h.joblib")
    pred = float(model.predict(X.iloc[[-1]])[0])
    res = metrics["hourly"][f"+{h}h"]
    out["hourly"].append({
        "h": h, "valid_utc": (t0 + pd.Timedelta(hours=h)).isoformat(),
        "wtmp_f": F(pred), "mae_f": res[res["best"]]["test_mae_f"],
    })
    print(f"+{h:>2}h  {F(pred)}F  (±{res[res['best']]['test_mae_f']}F)")

today = t0.normalize()
for k in features7.DAILY_HORIZONS:
    X, _ = features7.build_daily(hourly_buoy, wx, k)
    if today not in X.index:
        continue
    model = joblib.load(f"models/DAILY_{k}d.joblib")
    pred = float(model.predict(X.loc[[today]])[0])
    res = metrics["daily"][f"D+{k}"]
    valid = today + pd.Timedelta(days=k)
    out["daily"].append({
        "k": k, "date": valid.strftime("%Y-%m-%d"),
        "label": valid.strftime("%a"), "wtmp_f": F(pred),
        "mae_f": res[res["best"]]["test_mae_f"],
    })
    print(f"D+{k} {valid:%a %m-%d}  {F(pred)}F  (±{res[res['best']]['test_mae_f']}F)")

pathlib.Path("site/reports").mkdir(parents=True, exist_ok=True)
for png in ["model_comparison.png", "error_analysis.png", "correlations.png"]:
    src = pathlib.Path("reports") / png
    if src.exists():
        shutil.copy(src, pathlib.Path("site/reports") / png)

with open("site/data.json", "w") as fh:
    json.dump(out, fh, indent=2)
print("wrote site/data.json and copied figures to site/reports/")
