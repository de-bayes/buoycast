"""Error analysis for the water-temp forecaster. Fits the production model
class (lasso pipeline) at every horizon from +1 h to +24 h, scores the
untouched test weeks, and draws a four-panel report:

  1. error growth funnel: median / IQR / P90 absolute error vs horizon,
     with persistence for scale
  2. signed error distributions at +3/6/12/24 h (bias and spread)
  3. where the misses live: MAE binned by how much the water actually moved
  4. test-window timeline: actual vs +12 h predictions at their valid times

All temperatures in deg F. Writes reports/error_analysis.png.
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LassoCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import features

TEST_HOURS = 24 * 21
HORIZONS = list(range(1, 25))
CF = 1.8  # deg C error to deg F error


def lasso():
    return make_pipeline(
        SimpleImputer(strategy="median"), StandardScaler(),
        LassoCV(n_alphas=20, max_iter=5000, precompute=False, cv=TimeSeriesSplit(3), n_jobs=-1),
    )


df = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
X_all = features.build(df)

err_model, err_pers, keep = {}, {}, {}
for h in HORIZONS:
    y = df["WTMP"].shift(-h)
    ok = y.notna() & df["WTMP"].notna()
    X, yv, now = X_all[ok], y[ok], df.loc[ok, "WTMP"]
    split = len(X) - TEST_HOURS
    m = lasso()
    m.fit(X.iloc[:split], yv.iloc[:split])
    pred = pd.Series(m.predict(X.iloc[split:]), index=yv.index[split:])
    err_model[h] = (pred - yv.iloc[split:]) * CF
    err_pers[h] = (now.iloc[split:] - yv.iloc[split:]) * CF
    keep[h] = {"pred": pred, "true": yv.iloc[split:], "now": now.iloc[split:]}
    print(f"+{h:>2}h  model MAE {err_model[h].abs().mean():.2f}F  persistence {err_pers[h].abs().mean():.2f}F")

plt.style.use("dark_background")
C = {"bg": "#0a0c0e", "panel": "#101418", "ink": "#cfdce8", "red": "#ff4d4d",
     "green": "#3ddc6a", "yellow": "#ffd23e", "cyan": "#39c2ff", "magenta": "#ff5bd1", "faint": "#5d7283"}
fig = plt.figure(figsize=(13, 14), facecolor=C["bg"])
gs = fig.add_gridspec(3, 2, hspace=0.42, wspace=0.26, left=0.07, right=0.96, top=0.94, bottom=0.05)
for_ax = lambda ax: (ax.set_facecolor(C["panel"]), ax.grid(alpha=0.15), ax.tick_params(colors=C["ink"]))

# 1. error growth funnel
ax = fig.add_subplot(gs[0, :])
for_ax(ax)
q50 = [err_model[h].abs().median() for h in HORIZONS]
q25 = [err_model[h].abs().quantile(0.25) for h in HORIZONS]
q75 = [err_model[h].abs().quantile(0.75) for h in HORIZONS]
q90 = [err_model[h].abs().quantile(0.90) for h in HORIZONS]
p50 = [err_pers[h].abs().median() for h in HORIZONS]
p90 = [err_pers[h].abs().quantile(0.90) for h in HORIZONS]
ax.fill_between(HORIZONS, q25, q75, color=C["cyan"], alpha=0.25, label="model IQR")
ax.fill_between(HORIZONS, q75, q90, color=C["cyan"], alpha=0.10, label="model P75-P90")
ax.plot(HORIZONS, q50, color=C["cyan"], lw=2.2, label="model median |error|")
ax.plot(HORIZONS, q90, color=C["cyan"], lw=0.8, ls=":")
ax.plot(HORIZONS, p50, color=C["faint"], lw=1.6, ls="--", label="persistence median")
ax.plot(HORIZONS, p90, color=C["faint"], lw=0.8, ls=":", label="persistence P90")
ax.set_xlim(1, 24)
ax.set_xticks([1, 3, 6, 9, 12, 18, 24])
ax.set_xlabel("hours ahead", color=C["ink"])
ax.set_ylabel("absolute error (F)", color=C["ink"])
ax.set_title("How error grows with lead time (test weeks, lasso at every horizon)", color="w", loc="left")
ax.legend(frameon=False, labelcolor=C["ink"], fontsize=9, ncols=3)

# 2. signed error distributions
ax = fig.add_subplot(gs[1, 0])
for_ax(ax)
hs = [3, 6, 12, 24]
parts = ax.violinplot([err_model[h].dropna() for h in hs], positions=range(len(hs)), showmedians=True, widths=0.75)
for body in parts["bodies"]:
    body.set_facecolor(C["cyan"])
    body.set_alpha(0.45)
for k in ["cmedians", "cmins", "cmaxes", "cbars"]:
    parts[k].set_color(C["ink"])
ax.axhline(0, color=C["magenta"], lw=0.9, ls="--")
ax.set_xticks(range(len(hs)), [f"+{h}h" for h in hs])
ax.set_ylabel("signed error, forecast minus actual (F)", color=C["ink"])
ax.set_title("Bias and spread by horizon", color="w", loc="left")

# 3. MAE binned by realized 24h water movement
ax = fig.add_subplot(gs[1, 1])
for_ax(ax)
h = 24
move = (keep[h]["true"] - keep[h]["now"]).abs() * CF
bins = [0, 0.5, 1, 2, 3, 6, 15]
labels = ["0-0.5", "0.5-1", "1-2", "2-3", "3-6", "6+"]
cat = pd.cut(move, bins=bins, labels=labels, include_lowest=True)
g_model = err_model[h].abs().groupby(cat, observed=True).mean()
g_pers = err_pers[h].abs().groupby(cat, observed=True).mean()
counts = cat.value_counts().reindex(labels)
xp = np.arange(len(labels))
ax.bar(xp - 0.18, g_pers.reindex(labels), width=0.36, color=C["faint"], label="persistence")
ax.bar(xp + 0.18, g_model.reindex(labels), width=0.36, color=C["cyan"], label="model")
for i, n in enumerate(counts):
    ax.text(i, 0.05, f"n={n}", ha="center", color=C["faint"], fontsize=7)
ax.set_xticks(xp, labels)
ax.set_xlabel("how much the water actually moved in 24h (F)", color=C["ink"])
ax.set_ylabel("MAE of the +24h forecast (F)", color=C["ink"])
ax.set_title("The error lives in the swings", color="w", loc="left")
ax.legend(frameon=False, labelcolor=C["ink"], fontsize=9)

# 4. test-window timeline at +12h
ax = fig.add_subplot(gs[2, :])
for_ax(ax)
h = 12
true12, pred12 = keep[h]["true"], keep[h]["pred"]
valid = true12.index + pd.Timedelta(hours=h)
ax.plot(valid, true12 * CF + 32, color=C["ink"], lw=1.6, label="actual water temp")
ax.plot(valid, pred12 * CF + 32, color=C["cyan"], lw=1.2, label="+12h forecast at its valid time")
ax.fill_between(valid, true12 * CF + 32, pred12 * CF + 32, color=C["red"], alpha=0.25, label="miss")
ax.set_ylabel("water temp (F)", color=C["ink"])
ax.set_title("Test weeks, hour by hour: where the +12h forecast missed", color="w", loc="left")
ax.legend(frameon=False, labelcolor=C["ink"], fontsize=9, ncols=3)

fig.suptitle("Seiche error analysis · Wilmette buoy 45174 · held-out test weeks", color="w", fontsize=13, x=0.07, ha="left")
fig.savefig("reports/error_analysis.png", dpi=150, facecolor=C["bg"])
print("wrote reports/error_analysis.png")

# context numbers for the README / conversation
all_move = (df["WTMP"] - df["WTMP"].shift(24)).abs().dropna() * CF
print(f"\ncontext: median 24h water movement {all_move.median():.1f}F, P90 {all_move.quantile(0.9):.1f}F")
print(f"model +24h MAE {err_model[24].abs().mean():.2f}F vs persistence {err_pers[24].abs().mean():.2f}F")
