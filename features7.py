"""Feature builders for the weather-aware models. Hourly models get the
buoy-lag features plus aggregates of weather over the forecast window
(ERA5 in training, the GFS/HRRR forecast at inference). Daily models work
on calendar-day aggregates out to D+7."""

import numpy as np
import pandas as pd

import features

HOURLY_HORIZONS = [3, 6, 12, 24]
DAILY_HORIZONS = list(range(1, 8))


def prep_weather(wx):
    wx = wx.copy()
    rad = np.deg2rad(wx["wind_direction_10m"])
    wx["u"] = -wx["wind_speed_10m"] * np.sin(rad)
    wx["v"] = -wx["wind_speed_10m"] * np.cos(rad)
    return wx


def future_agg(wx, h):
    """Aggregates over the window (t, t+h], aligned to t."""
    f = pd.DataFrame(index=wx.index)
    f[f"fut_u_{h}"] = wx["u"].rolling(h).mean().shift(-h)
    f[f"fut_v_{h}"] = wx["v"].rolling(h).mean().shift(-h)
    f[f"fut_wspd_{h}"] = wx["wind_speed_10m"].rolling(h).mean().shift(-h)
    f[f"fut_t2m_{h}"] = wx["temperature_2m"].rolling(h).mean().shift(-h)
    f[f"fut_solar_{h}"] = wx["shortwave_radiation"].rolling(h).mean().shift(-h)
    f[f"fut_gust_{h}"] = wx["wind_gusts_10m"].rolling(h).max().shift(-h)
    return f


def build_hourly(buoy_df, wx, h):
    """Buoy-lag features joined with forecast-window weather for horizon h."""
    base = features.build(buoy_df)
    wx = prep_weather(wx)
    fut = future_agg(wx, h)
    X = base.join(fut, how="left")
    X[f"fut_airwater_{h}"] = X[f"fut_t2m_{h}"] - buoy_df["WTMP"]
    return X


def daily_frames(buoy_df, wx):
    """Calendar-day aggregates: buoy daily mean water temp (12+ valid hours)
    and daily weather summaries."""
    counts = buoy_df["WTMP"].resample("1D").count()
    bday = buoy_df["WTMP"].resample("1D").mean().where(counts >= 12)
    atday = buoy_df["ATMP"].resample("1D").mean()

    wx = prep_weather(wx)
    wd = pd.DataFrame({
        "u": wx["u"].resample("1D").mean(),
        "v": wx["v"].resample("1D").mean(),
        "wspd": wx["wind_speed_10m"].resample("1D").mean(),
        "gust": wx["wind_gusts_10m"].resample("1D").max(),
        "t2m": wx["temperature_2m"].resample("1D").mean(),
        "t2m_max": wx["temperature_2m"].resample("1D").max(),
        "solar": wx["shortwave_radiation"].resample("1D").sum(),
    })
    return bday, atday, wd


def build_daily(buoy_df, wx, k):
    """One row per anchor day D: buoy state at D plus the weather of target
    day D+k and the cumulative weather from D+1 through D+k. Target is the
    daily mean water temp on D+k."""
    bday, atday, wd = daily_frames(buoy_df, wx)
    X = pd.DataFrame(index=bday.index)
    X["wtmp_now"] = bday
    X["wtmp_d1"] = bday - bday.shift(1)
    X["wtmp_d3"] = bday - bday.shift(3)
    X["wtmp_d7"] = bday - bday.shift(7)
    X["atmp_now"] = atday
    X["airwater_now"] = atday - bday

    tgt = wd.shift(-k)  # weather on day D+k
    for col in wd.columns:
        X[f"day{k}_{col}"] = tgt[col]
    cum = wd.rolling(k).mean().shift(-k)  # mean over D+1 .. D+k
    for col in ["u", "v", "wspd", "t2m", "solar"]:
        X[f"cum{k}_{col}"] = cum[col]
    X[f"cum{k}_airwater"] = cum["t2m"] - bday

    doy = X.index.dayofyear.to_numpy()
    X["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    X["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)

    y = bday.shift(-k)
    return X, y
