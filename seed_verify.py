"""One-time seed for the Track Record log so the page is populated on day one.

Reconstructs the most recent ~21 days of forecasts with the production quantile
models over observed/reanalysis weather (a perfect-prog hindcast), anchored
exactly as production does, and appends them to data/fc_log.jsonl tagged origin
"hindcast". Genuine "live" forecasts from publish.py supersede them as they
accumulate.

Honesty caveat (also stated on the page): the current weekly model has trained
on data inside this window, so reconstructed errors can run slightly optimistic.
The 9-season rolling backtest (genuinely out-of-sample) is the rigorous skill
claim; this seed exists only for immediate recent visualization.

Run once: python3 seed_verify.py
"""

import joblib
import numpy as np
import pandas as pd

import featuresq
import verify

SEED_DAYS = 21
STEP_H = 3                       # one reconstructed base every 3 h keeps the log lean
TAU = 8.0
F = lambda c: c * 1.8 + 32
QMAP = {0.05: "p05", 0.25: "p25", 0.5: "p50", 0.75: "p75", 0.95: "p95"}

buoy = pd.read_csv("data/buoy.csv", index_col=0, parse_dates=True)
wx = pd.read_csv("data/weather.csv", index_col=0, parse_dates=True)
models = {q: joblib.load(f"models/q_{int(q * 100):02d}.joblib") for q in featuresq.QUANTILES}
feat_cols = list(models[0.5].feature_names_in_)

obs = buoy["WTMP"].dropna()
now = obs.index.max()
start = now - pd.Timedelta(days=SEED_DAYS)
# bases far enough back that at least the short leads have resolved
bases = [b for b in obs.index if start <= b <= now - pd.Timedelta(hours=6)][::STEP_H]
if not bases:
    raise SystemExit("no base times in the seed window")
print(f"seeding {len(bases)} reconstructed forecasts over {SEED_DAYS}d "
      f"({bases[0]:%Y-%m-%d} to {bases[-1]:%Y-%m-%d})")

# +1h median for the anchor (obs_now - model's +1h call), decaying with lead
X1 = featuresq.assemble(buoy, wx, 1).reindex(columns=feat_cols).loc[bases]
p1 = models[0.5].predict(X1)
delta = obs.loc[bases].to_numpy() - p1

# per lead: predict all five quantiles, anchor, store aligned to bases
anch = {}
for h in verify.LEADS:
    X = featuresq.assemble(buoy, wx, h).reindex(columns=feat_cols).loc[bases]
    decay = float(np.exp(-(h - 1) / TAU))
    stack = np.sort(np.vstack([models[q].predict(X) + delta * decay
                               for q in featuresq.QUANTILES]), axis=0)  # enforce monotone
    anch[h] = stack   # shape (5, n_bases), rows ordered by QUANTILES

for i, b in enumerate(bases):
    fc = {str(h): {QMAP[q]: round(F(anch[h][r, i]), 2)
                   for r, q in enumerate(featuresq.QUANTILES)}
          for h in verify.LEADS}
    verify.append(b, fc, F(obs.loc[b]), generated_utc=b.isoformat(), origin="hindcast")

print(f"seeded; log now has {len(verify._read())} entries -> data/fc_log.jsonl")
