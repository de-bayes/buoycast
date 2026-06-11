"""Candidate feature blocks from the three new live data streams, built to
align with featuresq.stack row order WITHOUT touching featuresq itself.
Promotion into the production stack only happens if validate_streams.py's
pre-registered rules pass.

Availability discipline: every feature here uses only data that would have
existed at forecast time t. Satellite images carry a 1-day publication lag;
the LMHOFS future value is masked beyond +120 h because that is where the
live physics forecast ends.

  SAT   daily MUR satellite SST: buoy pixel, cross-shore gradients, basin
        mean and its 3-day trend, satellite-vs-buoy disagreement.
  PHYS  hourly LMHOFS physics-model surface temp at this exact station:
        level now, value at the valid time (h <= 120), the model's predicted
        change over the horizon, and its current bias vs the buoy.
  BEACH Chicago beach sensors (same shelf, ~25 km south): Ohio Street level,
        gap vs the buoy, 24 h trend.
"""

import numpy as np
import pandas as pd

import featuresq

SAT_PATH = "data/mursst.csv"
PHYS_PATH = "data/lmhofs.csv"
BEACH_PATH = "data/chibeach.csv"
PHYS_MAX_H = 120


def _hourly_asof_daily(daily, hourly_index, lag_days=1, limit_days=3):
    """Map a daily-indexed frame onto an hourly index: at hour t use the row
    for date(t) - lag_days, tolerating up to limit_days of missing images."""
    d = daily.copy()
    d.index = pd.to_datetime(d.index).tz_localize("UTC") + pd.Timedelta(days=lag_days)
    d = d.reindex(d.index.union(hourly_index)).ffill(limit=24 * limit_days)
    return d.reindex(hourly_index)


def sat_hourly(buoy_df):
    daily = pd.read_csv(SAT_PATH, index_col=0, parse_dates=True)
    daily["sat_basin_d3"] = daily["sat_basin"] - daily["sat_basin"].shift(3)
    h = _hourly_asof_daily(daily, buoy_df.index)
    out = pd.DataFrame(index=buoy_df.index)
    out["sat_x0"] = h["sat_x0"]
    out["sat_basin"] = h["sat_basin"]
    out["sat_grad_near"] = h["sat_x0"] - h["sat_x2"]
    out["sat_grad_far"] = h["sat_x0"] - h["sat_x8"]
    out["sat_basin_d3"] = h["sat_basin_d3"]
    out["sat_err"] = h["sat_x0"] - buoy_df["WTMP"]
    return out


def phys_series(buoy_index):
    s = pd.read_csv(PHYS_PATH, index_col=0, parse_dates=True)["lmhofs_sst"]
    full = s.reindex(s.index.union(buoy_index)).ffill(limit=2)
    return full


def beach_hourly(buoy_df):
    b = pd.read_csv(BEACH_PATH, index_col=0, parse_dates=True)
    s = b["beach_ohio"].reindex(b.index.union(buoy_df.index)).ffill(limit=3)
    s = s.reindex(buoy_df.index)
    out = pd.DataFrame(index=buoy_df.index)
    out["beach_ohio"] = s
    out["beach_gap"] = s - buoy_df["WTMP"]
    out["beach_d24"] = s - s.shift(24)
    return out


def build_blocks(buoy_df, horizons=featuresq.HSET, sets=("SAT", "PHYS", "BEACH")):
    """Extra feature frame aligned to featuresq.stack(buoy, wx) row order:
    same horizon loop, same ok mask (y at t+h and WTMP at t both present)."""
    per_t = {}
    if "SAT" in sets:
        per_t["SAT"] = sat_hourly(buoy_df)
    if "BEACH" in sets:
        per_t["BEACH"] = beach_hourly(buoy_df)
    phys = phys_series(buoy_df.index) if "PHYS" in sets else None

    blocks = []
    for h in horizons:
        y = buoy_df["WTMP"].shift(-h)
        ok = y.notna() & buoy_df["WTMP"].notna()
        idx = buoy_df.index[ok]
        block = pd.DataFrame(index=idx)
        for key in per_t:
            block = block.join(per_t[key].loc[idx])
        if phys is not None:
            now = phys.reindex(idx).to_numpy()
            block["lmhofs_now"] = now
            if h <= PHYS_MAX_H:
                fut = phys.reindex(idx + pd.Timedelta(hours=h)).to_numpy()
            else:
                fut = np.full(len(idx), np.nan)
            block["lmhofs_fut"] = fut
            block["lmhofs_delta"] = fut - now
            block["lmhofs_err"] = buoy_df["WTMP"].loc[idx].to_numpy() - now
        blocks.append(block)
    return pd.concat(blocks, ignore_index=True)


COLS = {"SAT": ["sat_x0", "sat_basin", "sat_grad_near", "sat_grad_far",
                "sat_basin_d3", "sat_err"],
        "PHYS": ["lmhofs_now", "lmhofs_fut", "lmhofs_delta", "lmhofs_err"],
        "BEACH": ["beach_ohio", "beach_gap", "beach_d24"]}
