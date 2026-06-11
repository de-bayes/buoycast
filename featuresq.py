"""Features for the horizon-conditioned quantile model. One row = (time t,
horizon h): buoy state at t, weather aggregated over (t, t+h] under GENERIC
column names, and h itself as a feature, so a single model serves every
horizon from +1 h to +168 h.

assemble() is the single source of truth for the feature columns; train.py,
backtest.py, and publish.py all go through it (or inference_rows for live),
so the column set can never drift between fit and predict.

History note: an across-lake neighbor buoy (45026), season degree-day, and
cumulative wind-stress features were trialled here. On the 131k-pair nine-season
backtest they carried near-zero permutation importance and slightly raised MAE
(over-reaction variance), so they were dropped. Only dewpoint depression
(evaporative cooling) survived; the neighbor is still fetched for possible
later use. See DOCS / git history."""

import pathlib

import numpy as np
import pandas as pd

import features
import features7

HSET = [1, 2, 3, 6, 9, 12, 18, 24, 36, 48, 60, 72, 96, 120, 144, 168]
QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]

FUT_COLS = ["fut_u", "fut_v", "fut_wspd", "fut_t2m", "fut_solar", "fut_gust",
            "fut_dewdep", "fut_airwater"]

# open-lake buoy still fetched (data/buoy_neighbor.csv) but not used as a
# feature; it added variance without skill on the backtest.
NEIGHBOR_STATION = "45026"
NEIGHBOR_PATH = "data/buoy_neighbor.csv"


def load_neighbor():
    p = pathlib.Path(NEIGHBOR_PATH)
    if not p.exists():
        return None
    return pd.read_csv(p, index_col=0, parse_dates=True)


def future_generic(wx, h, wtmp):
    f = pd.DataFrame(index=wx.index)
    f["fut_u"] = wx["u"].rolling(h).mean().shift(-h)
    f["fut_v"] = wx["v"].rolling(h).mean().shift(-h)
    f["fut_wspd"] = wx["wind_speed_10m"].rolling(h).mean().shift(-h)
    f["fut_t2m"] = wx["temperature_2m"].rolling(h).mean().shift(-h)
    f["fut_solar"] = wx["shortwave_radiation"].rolling(h).mean().shift(-h)
    f["fut_gust"] = wx["wind_gusts_10m"].rolling(h).max().shift(-h)
    # mean dewpoint depression over the window: how hard evaporation pulls heat
    # off the surface (the one weather covariate the trial features kept)
    f["fut_dewdep"] = (wx["temperature_2m"] - wx["dew_point_2m"]).rolling(h).mean().shift(-h)
    f["fut_airwater"] = f["fut_t2m"] - wtmp
    return f


def assemble(buoy_df, wx, h):
    """Full feature frame for a fixed horizon h, indexed by base time. Same
    column set for every horizon and for live inference."""
    base = features.build(buoy_df)
    wxp = features7.prep_weather(wx)
    X = base.join(future_generic(wxp, h, buoy_df["WTMP"]), how="left")
    X["h"] = float(h)
    return X


def stack(buoy_df, wx, horizons=HSET):
    """Stacked training matrix across horizons. Returns X, y, base_time, h."""
    blocks, ys, ts, hs = [], [], [], []
    for h in horizons:
        X = assemble(buoy_df, wx, h)
        y = buoy_df["WTMP"].shift(-h)
        ok = y.notna() & buoy_df["WTMP"].notna()
        blocks.append(X[ok])
        ys.append(y[ok])
        ts.append(X.index[ok])
        hs.append(np.full(int(ok.sum()), h))
    Xs = pd.concat(blocks, ignore_index=True)
    return (Xs, pd.concat(ys, ignore_index=True),
            pd.DatetimeIndex(np.concatenate([t.values for t in ts])), np.concatenate(hs))


def inference_rows(buoy_df, wx, t0, horizons):
    """Feature rows at a single base time t0 for each horizon (live forecast)."""
    base = features.build(buoy_df).loc[[t0]]
    wxp = features7.prep_weather(wx)
    after = wxp.loc[wxp.index > t0]
    wtmp0 = buoy_df["WTMP"].loc[t0]
    rows = []
    for h in horizons:
        win = after.iloc[:h]
        row = base.copy()
        row["fut_u"] = win["u"].mean()
        row["fut_v"] = win["v"].mean()
        row["fut_wspd"] = win["wind_speed_10m"].mean()
        row["fut_t2m"] = win["temperature_2m"].mean()
        row["fut_solar"] = win["shortwave_radiation"].mean()
        row["fut_gust"] = win["wind_gusts_10m"].max()
        row["fut_dewdep"] = (win["temperature_2m"] - win["dew_point_2m"]).mean()
        row["fut_airwater"] = row["fut_t2m"].iloc[0] - wtmp0
        row["h"] = float(h)
        rows.append(row)
    return pd.concat(rows, ignore_index=True)
