"""Build reports/buoycast_brief.pdf: the two-page plain-language brief for
sharing (Twitter -> PDF hosted on mccomb.ca). Numbers match the public
explainer at mccomb.ca/ml (nine-season backtest means)."""

import json
import pathlib
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

ACCENT = "#1257a0"; INK = "#16181d"; MUTED = "#5b6470"; FAINT = "#aab2bb"
AMBER = "#b45309"; RULE = "#e7e7e7"
plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Lora", "Georgia", "Times New Roman", "DejaVu Serif"],
    "text.color": INK, "axes.edgecolor": RULE, "axes.labelcolor": MUTED,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.titlecolor": INK,
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.grid": True, "grid.color": RULE, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 8.5,
})

bt = json.load(open("models/backtest.json"))
HS = bt["horizons"]
mae, maep = bt["mean_mae"], bt["mean_mae_persist"]
pairs = pd.read_csv("data/report_pairs.csv", parse_dates=["t"])
pairs["aerr"] = (pairs.p50 - pairs.y).abs() * 1.8

A4 = (8.27, 11.69); M = 0.085
pdf = PdfPages("reports/buoycast_brief.pdf")

# ---------------------------------------------------------------- page 1
fig = plt.figure(figsize=A4)
logo = np.array(Image.open("/tmp/logo_print.png"))
ax_logo = fig.add_axes([1 - M - 0.095, 0.862, 0.095, 0.095 * (8.27/11.69) * (640/512) * 1.42])
ax_logo.imshow(logo); ax_logo.axis("off")
fig.text(M, 0.952, "BUOYCAST · A SHORT BRIEF", fontsize=7.5, color=ACCENT,
         weight="bold", family="serif")
fig.text(M, 0.922, "A machine-learning forecast for\nLake Michigan water temperature", fontsize=18.5,
         weight="bold", va="top", linespacing=1.22)
fig.text(M, 0.862, "Ryan McComb · June 2026 · NDBC buoy 45174, Evanston-Wilmette shoreline",
         fontsize=8.5, color=MUTED)
fig.text(M, 0.845, "Status: not live yet, in final testing", fontsize=8.5, color=MUTED, style="italic")
fig.add_artist(plt.Line2D([M, 1-M], [0.832, 0.832], color=RULE, lw=0.8, transform=fig.transFigure))

body1 = (
    "Two kilometres off the Wilmette shore there is a NOAA buoy that reports the water "
    "temperature every ten minutes, May through November. Swimmers check it constantly, "
    "because this corner of Lake Michigan is moody: one hard north wind can tear the warm "
    "surface layer off the beach overnight and drop the water ten degrees while everyone sleeps.\n\n"
    "Buoycast is my attempt to forecast that buoy. It is deliberately simple machinery: "
    "gradient-boosted decision trees (scikit-learn, no neural networks), trained on ten seasons "
    "of history, 2016 through 2026. Each training example pairs one moment of the lake, described "
    "by 46 numbers (recent water temperatures, wind, sun, air temperature, the season clock, and "
    "the weather forecast over the coming window) with what the water actually did afterward. "
    "That gives the model 599,000 examples to learn from.\n\n"
    "It forecasts every hour out to seven days. Five copies of the model predict five "
    "percentiles, so the output is not a single number but a band; the whole thing is run across "
    "34 different weather-model futures, so the band widens exactly when the weather models "
    "genuinely disagree; and every forecast is pinned to the buoy's live reading at hour one."
)
fig.text(M, 0.808, body1, fontsize=9.6, va="top", linespacing=1.6, wrap=True)

# numbers strip
stats_y = 0.50
for i, (label, val) in enumerate([
        ("TRAINING EXAMPLES", "599,000"),
        ("INPUTS PER HOUR", "46"),
        ("SEASONS REPLAYED", "9"),
        ("VERIFIED TEST FORECASTS", "131,745"),
        ("REFRESH", "10 min"),
]):
    x = M + i * (1 - 2 * M) / 5
    fig.text(x, stats_y, label, fontsize=5.8, color=MUTED)
    fig.text(x, stats_y - 0.028, val, fontsize=13, color=INK, weight="bold")
fig.add_artist(plt.Line2D([M, 1-M], [stats_y + 0.022, stats_y + 0.022], color=RULE, lw=0.8, transform=fig.transFigure))
fig.add_artist(plt.Line2D([M, 1-M], [stats_y - 0.048, stats_y - 0.048], color=RULE, lw=0.8, transform=fig.transFigure))

ax = fig.add_axes([M, 0.135, 1 - 2 * M, 0.285])
for f in bt["folds"]:
    ax.plot(HS, f["mae"], color=ACCENT, alpha=0.15, lw=0.8)
ax.plot(HS, mae, color=ACCENT, lw=2.4, marker="o", ms=3.5, label="buoycast")
ax.plot(HS, maep, color=MUTED, lw=1.8, ls="--", label='"the water stays the same" (persistence)')
ax.set_xticks([1, 24, 48, 72, 96, 120, 144, 168])
ax.set_xlabel("forecast lead (hours ahead)")
ax.set_ylabel("mean absolute error (°F)")
ax.set_title("Figure 1 · How far off it is, by lead time: nine seasons replayed honestly", loc="left")
ax.legend(frameon=False, fontsize=8.5, loc="upper left")
fig.text(M, 0.072,
         "Every number comes from data the model had never seen: it was retrained nine times, once per season "
         "2018-2026, and graded only on held-out weeks (131,745 forecast-versus-outcome pairs). Thin lines are "
         "individual seasons. At one day the lake barely moves, so beating persistence is nearly impossible; "
         "from two days out the model pulls away, and at a week it is roughly twice as accurate.",
         fontsize=7.8, color=MUTED, va="top", linespacing=1.5, wrap=True)
fig.text(M, 0.028, "buoycast brief · page 1 of 2", fontsize=7, color=FAINT)
pdf.savefig(fig); plt.close(fig)

# ---------------------------------------------------------------- page 2
fig = plt.figure(figsize=A4)
fig.text(M, 0.945, "RESULTS ON HELD-OUT SEASONS", fontsize=7.5, color=ACCENT, weight="bold")
fig.add_artist(plt.Line2D([M, 1-M], [0.935, 0.935], color=RULE, lw=0.8, transform=fig.transFigure))

# the table, same numbers as the mccomb.ca/ml explainer
rows = [("lead", "model", '"no change"', "edge")]
idx = {1: None, 24: None, 72: None, 168: None}
for h in idx: idx[h] = HS.index(h)
for h, lab in [(1, "+1 hour"), (24, "+1 day"), (72, "+3 days"), (168, "+7 days")]:
    m_, p_ = mae[idx[h]], maep[idx[h]]
    edge = "tie" if abs(m_ - p_) < 0.06 else f"+{(1 - m_/p_)*100:.0f}%"
    rows.append((lab, f"{m_:.2f} °F", f"{p_:.2f} °F", edge))
ax = fig.add_axes([M, 0.745, 0.52, 0.155]); ax.axis("off")
tab = ax.table(cellText=[r for r in rows[1:]], colLabels=rows[0], loc="center", cellLoc="center")
tab.auto_set_font_size(False); tab.set_fontsize(9); tab.scale(1, 1.6)
for k, cell in tab.get_celld().items():
    cell.set_edgecolor(RULE)
    if k[0] == 0: cell.set_text_props(color=MUTED, fontsize=7.5); cell.set_facecolor("#f7f7f7")

fig.text(M + 0.56, 0.895,
         "Half of all one-day forecasts miss by under half a degree. "
         "The published band is calibrated on those nine replayed seasons, "
         "so when it says 90 percent, it holds the real outcome at least "
         "90 percent of the time. When the lake is about to do something "
         "violent, the band widens and says so.",
         fontsize=9, va="top", linespacing=1.6, wrap=True,
         color=INK)

# figure 2: typical vs bad day
ax = fig.add_axes([M, 0.455, 1 - 2 * M, 0.245])
med = pairs.groupby("h").aerr.median().reindex(HS)
p90 = pairs.groupby("h").aerr.quantile(0.9).reindex(HS)
ax.plot(HS, med, color=ACCENT, lw=2.2, label="typical day (median miss)")
ax.plot(HS, p90, color=AMBER, lw=2.2, label="bad day (90th percentile miss)")
ax.set_xticks([1, 24, 72, 120, 168])
ax.set_xlabel("forecast lead (hours)"); ax.set_ylabel("absolute error (°F)")
ax.set_title("Figure 2 · Typical day vs bad day. The gap is why the forecast carries a band", loc="left")
ax.legend(frameon=False, fontsize=8.5)
fig.text(M, 0.385,
         "The hard days are real: autumn wind events (upwelling) can drop this shoreline 10 to 16 degrees in a day, "
         "and the worst one-day miss across nine seasons was 10.5 °F during exactly such a storm. The model's answer "
         "is honesty rather than bravado: those are the days its uncertainty band visibly opens up.",
         fontsize=7.8, color=MUTED, va="top", linespacing=1.5, wrap=True)

fig.text(M, 0.315, "WHAT HAPPENS NEXT", fontsize=7.5, color=ACCENT, weight="bold")
fig.text(M, 0.300,
    "The live version is in final testing: a dashboard that refreshes every ten minutes against the "
    "buoy, retrains itself every Sunday, and runs on one small cloud VM and open data end to end. "
    "It will be public soon.",
    fontsize=9.2, va="top", linespacing=1.6, wrap=True)
fig.text(M, 0.242, "CREDIT WHERE IT IS DUE", fontsize=7.5, color=ACCENT, weight="bold")
fig.text(M, 0.227,
    "None of these ideas are new; they are old, public ideas applied carefully. The validation "
    "approach, replaying whole hidden seasons and grading the model cold, runs parallel to the "
    "VoteHub 2026 midterm methodology, which is mainly the work of Zachary Donnini; most of what I "
    "know about checking a forecast honestly comes from that write-up and from questions Zachary "
    "has answered for me. Data: NOAA NDBC (the buoy), ERA5 reanalysis (Copernicus), and the GFS, "
    "ECMWF, ICON, and GEM weather models via Open-Meteo, all open and free.",
    fontsize=9.2, va="top", linespacing=1.6, wrap=True)
fig.text(M, 0.118, "STACK", fontsize=7.5, color=ACCENT, weight="bold")
fig.text(M, 0.103,
    "Python, scikit-learn, pandas; one HistGradientBoostingRegressor per quantile; conformal "
    "calibration on pooled out-of-sample residuals; anchor-blended to the live observation.",
    fontsize=8.6, color=MUTED, va="top", linespacing=1.55, wrap=True)
fig.text(M, 0.045, "Ryan McComb · mccomb.ca · June 2026", fontsize=8, color=MUTED)
fig.text(1 - M, 0.045, "buoycast brief · page 2 of 2", fontsize=7, color=FAINT, ha="right")
pdf.savefig(fig); plt.close(fig)

info = pdf.infodict()
info["Title"] = "Buoycast: a machine-learning forecast for Lake Michigan water temperature"
info["Author"] = "Ryan McComb"
pdf.close()
print("wrote reports/buoycast_brief.pdf")
