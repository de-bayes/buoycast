"""Historical correlation study: which weather drivers move nearshore water
temperature, and does knowing the FUTURE window (what a weather forecast
provides) beat knowing only the past? Two panels:

  1. paired bars: correlation of next-24h water change with each driver
     measured over the past 24 h vs over the forecast window itself
  2. window sweep: how the future-window correlations build with window length

Writes reports/correlations.png. This figure is the justification for the
future-covariate features in the 7-day model."""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

buoy = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
wx = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)
df = buoy.join(wx, how="inner")

rad = np.deg2rad(df["wind_direction_10m"])
df["u"] = -df["wind_speed_10m"] * np.sin(rad)
df["v"] = -df["wind_speed_10m"] * np.cos(rad)
dw24 = (df["WTMP"].shift(-24) - df["WTMP"]) * 1.8


def r(series):
    ok = series.notna() & dw24.notna()
    return float(np.corrcoef(series[ok], dw24[ok])[0, 1])


past = lambda s: s.rolling(24).mean()
fut = lambda s: s.rolling(24).mean().shift(-24)

DRIVERS = [
    ("air minus water temp", df["temperature_2m"] - df["WTMP"], fut(df["temperature_2m"]) - df["WTMP"]),
    ("wind speed", past(df["wind_speed_10m"]), fut(df["wind_speed_10m"])),
    ("solar radiation", past(df["shortwave_radiation"]), fut(df["shortwave_radiation"])),
    ("N-S wind (upwelling axis)", past(df["v"]), fut(df["v"])),
    ("gusts", df["wind_gusts_10m"].rolling(24).max(), df["wind_gusts_10m"].rolling(24).max().shift(-24)),
    ("E-W wind", past(df["u"]), fut(df["u"])),
]

print("driver                         past24h   future24h")
rows = []
for name, p, f in DRIVERS:
    rows.append((name, r(p), r(f)))
    print(f"{name:>28}:  {rows[-1][1]:+.3f}   {rows[-1][2]:+.3f}")

windows = [6, 12, 24, 36, 48, 72, 96]
sweep = {
    "wind speed": [r(df["wind_speed_10m"].rolling(w).mean().shift(-w)) for w in windows],
    "air minus water": [r(df["temperature_2m"].rolling(w).mean().shift(-w) - df["WTMP"]) for w in windows],
    "solar": [r(df["shortwave_radiation"].rolling(w).mean().shift(-w)) for w in windows],
    "N-S wind": [r(df["v"].rolling(w).mean().shift(-w)) for w in windows],
}

# export the underlying numbers so the site can draw this interactively
import json
with open("reports/correlations.json", "w") as fh:
    json.dump({
        "drivers": [{"name": n, "past": round(p, 4), "future": round(f, 4)} for n, p, f in rows],
        "windows": windows,
        "sweep": {k: [round(v, 4) for v in vs] for k, vs in sweep.items()},
    }, fh)
print("wrote reports/correlations.json")

plt.style.use("dark_background")
BG, PANEL, INK, CYAN, FAINT, YEL = "#0a0c0e", "#101418", "#cfdce8", "#39c2ff", "#5d7283", "#ffd23e"
fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.6), facecolor=BG)
fig.subplots_adjust(left=0.19, right=0.97, bottom=0.13, top=0.84, wspace=0.2)

ax = axes[0]
ax.set_facecolor(PANEL)
names = [d[0] for d in rows][::-1]
pv = [abs(d[1]) for d in rows][::-1]
fv = [abs(d[2]) for d in rows][::-1]
yp = np.arange(len(names))
ax.barh(yp + 0.19, pv, height=0.36, color=FAINT, label="past 24h (what the buoy knows)")
ax.barh(yp - 0.19, fv, height=0.36, color=CYAN, label="forecast window (what a wx forecast adds)")
ax.set_yticks(yp, names)
ax.set_xlabel("|correlation| with next-24h water temp change", color=INK)
ax.set_title("The signal lives in the forecast window", color="w", loc="left")
ax.legend(frameon=False, labelcolor=INK, fontsize=9, loc="lower right")
ax.grid(alpha=0.15, axis="x")
ax.tick_params(colors=INK)

ax = axes[1]
ax.set_facecolor(PANEL)
for (name, ys), color in zip(sweep.items(), [CYAN, "#ff4d4d", YEL, "#3ddc6a"]):
    ax.plot(windows, [abs(v) for v in ys], marker="o", lw=2, color=color, label=name)
ax.set_xlabel("future window length (hours)", color=INK)
ax.set_ylabel("|correlation| with next-24h water change", color=INK)
ax.set_title("Sustained conditions matter more than snapshots", color="w", loc="left")
ax.set_xticks(windows)
ax.legend(frameon=False, labelcolor=INK, fontsize=9)
ax.grid(alpha=0.15)
ax.tick_params(colors=INK)

fig.suptitle("buoycast driver study · Wilmette buoy 45174 + ERA5 reanalysis, 2021-2026", color="w", x=0.19, ha="left", fontsize=13)
fig.savefig("reports/correlations.png", dpi=150, facecolor=BG)
print("wrote reports/correlations.png")
