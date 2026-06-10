"""Pull the latest Wilmette buoy observations, run the trained models, and
print a human-readable forecast (plus forecast.json for anything downstream)."""

import json
from datetime import timedelta

import joblib
import pandas as pd

import buoy
import features


def f(c):
    return c * 1.8 + 32


def ft(m):
    return m * 3.28084


hourly = buoy.to_hourly([buoy.fetch_realtime()])
X = features.build(hourly)
row = X.iloc[[-1]]
t0 = hourly.index[-1]

with open("models/metrics.json") as fh:
    metrics = json.load(fh)

last_valid = hourly.ffill().iloc[-1]  # newest reading per sensor; some lag a few minutes
now_wtmp, now_wvht = last_valid["WTMP"], last_valid["WVHT"]
now_wspd, now_gst = last_valid["WSPD"], last_valid["GST"]
print(f"WILMETTE BUOY 45174 · {t0:%a %b %d %H:%M} UTC")
print(f"now: water {f(now_wtmp):.1f}F · waves {ft(now_wvht):.1f} ft · "
      f"wind {now_wspd * 1.944:.0f} kt gusting {now_gst * 1.944:.0f}\n")

out = {"valid_utc": t0.isoformat(), "now": {"wtmp_f": round(f(now_wtmp), 1), "wvht_ft": round(ft(now_wvht), 2)}}
for target, label, conv, unit in [("WTMP", "water", f, "F"), ("WVHT", "waves", ft, "ft")]:
    preds = {}
    for h in features.HORIZONS:
        m = joblib.load(f"models/{target}_{h}h.joblib")
        val = float(m.predict(row)[0])
        preds[f"+{h}h"] = round(conv(val), 2)
        m_info = metrics[f"{target}+{h}h"]
        when = (t0 + timedelta(hours=h)).strftime("%H:%M")
        skill = m_info["skill_vs_persistence"]
        note = "" if skill and skill > 0 else "  [no skill vs persistence, treat as current value]"
        mae_unit = m_info["mae"] * 1.8 if target == "WTMP" else ft(m_info["mae"])
        print(f"{label} +{h:>2}h ({when}Z): {conv(val):.1f} {unit}  "
              f"(holdout MAE ±{mae_unit:.1f} {unit}){note}")
    out[target.lower()] = preds
    print()

with open("forecast.json", "w") as fh:
    json.dump(out, fh, indent=2)
print("wrote forecast.json")
