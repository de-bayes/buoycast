"""Feature builder shared by train.py and forecast.py. Lags, deltas, rolling
wind vectors (the upwelling driver on this shoreline), and seasonal clocks.
HistGradientBoosting handles NaNs natively, so gaps stay NaN."""

import numpy as np
import pandas as pd

TARGETS = ["WTMP", "WVHT"]
HORIZONS = [3, 6, 12, 24]


def build(df):
    f = pd.DataFrame(index=df.index)
    rad = np.deg2rad(df["WDIR"])
    u = -df["WSPD"] * np.sin(rad)
    v = -df["WSPD"] * np.cos(rad)

    for col in ["WTMP", "WVHT", "ATMP", "WSPD", "GST", "PRES"]:
        f[col] = df[col]
    for lag in [1, 2, 3, 6, 12, 24]:
        f[f"wtmp_l{lag}"] = df["WTMP"].shift(lag)
        f[f"wvht_l{lag}"] = df["WVHT"].shift(lag)
    f["wtmp_d6"] = df["WTMP"] - df["WTMP"].shift(6)
    f["wtmp_d24"] = df["WTMP"] - df["WTMP"].shift(24)
    f["atmp_minus_wtmp"] = df["ATMP"] - df["WTMP"]
    f["pres_d3"] = df["PRES"] - df["PRES"].shift(3)

    f["u"] = u
    f["v"] = v
    for win in [6, 12, 24]:
        f[f"u_m{win}"] = u.rolling(win, min_periods=win // 2).mean()
        f[f"v_m{win}"] = v.rolling(win, min_periods=win // 2).mean()
        f[f"wspd_m{win}"] = df["WSPD"].rolling(win, min_periods=win // 2).mean()

    doy = f.index.dayofyear.to_numpy()
    hod = f.index.hour.to_numpy()
    f["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    f["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    f["hod_sin"] = np.sin(2 * np.pi * hod / 24)
    f["hod_cos"] = np.cos(2 * np.pi * hod / 24)
    return f
