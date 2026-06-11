"""Fetch hourly weather over the buoy site: ERA5 reanalysis for the training
years (archive API) and the GFS/HRRR forecast for the next 8 days (forecast
API). Same variables and units from both, so train and inference match.
Writes data/weather.csv (history) and data/weather_forecast.csv."""

import json
import urllib.request

import pandas as pd

LAT, LON = 42.05, -87.66
# dew_point_2m drives the evaporative-cooling signal; 850 hPa temp is omitted
# because the ERA5 archive returns it as null, which would break perfect-prog.
VARS = ("temperature_2m,dew_point_2m,wind_speed_10m,wind_direction_10m,"
        "wind_gusts_10m,shortwave_radiation,cloud_cover")

ARCHIVE = (
    "https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
    "&start_date=2016-04-01&end_date={end}&hourly=" + VARS +
    "&wind_speed_unit=ms&timezone=UTC"
)
# past_days=7 closes the gap between where ERA5 ends (~5 days back) and the
# forecast start, so live runs always have real weather over the recent window.
FORECAST = (
    "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
    "&hourly=" + VARS + "&wind_speed_unit=ms&forecast_days=8&past_days=7&timezone=UTC"
)

# Multi-model ensemble: independent operational global models. Running the
# water-temp model on each and taking the spread gives a physical estimate of
# how much the forecast uncertainty is driven by weather-model disagreement.
ENSEMBLE_MODELS = ["gfs_seamless", "ecmwf_ifs025", "icon_seamless", "gem_seamless"]
VARS_ENS = ("temperature_2m,dew_point_2m,wind_speed_10m,wind_direction_10m,"
            "wind_gusts_10m,shortwave_radiation")
FORECAST_ENS = (
    "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
    "&hourly=" + VARS_ENS + "&wind_speed_unit=ms&forecast_days=8&past_days=7"
    "&timezone=UTC&models={model}"
)

# True perturbed-physics ensemble: NOAA GEFS, 31 members (control + 30), via
# Open-Meteo's ensemble endpoint. Same variables/units as everything else.
GEFS_URL = (
    "https://ensemble-api.open-meteo.com/v1/ensemble?latitude={lat}&longitude={lon}"
    "&hourly=" + VARS_ENS + "&wind_speed_unit=ms&forecast_days=8&past_days=7"
    "&timezone=UTC&models=gfs025"
)


def member_forecasts(models=ENSEMBLE_MODELS):
    """{model_name: hourly weather frame} for each deterministic model that responds."""
    out = {}
    for m in models:
        try:
            out[m] = frame(get(FORECAST_ENS.format(lat=LAT, lon=LON, model=m)))
        except Exception as e:  # a single model dropping out is tolerable
            print(f"  member {m} skipped ({e})")
    return out


def gefs_members():
    """{label: hourly frame} for the 31 GEFS perturbed members. Member columns
    arrive suffixed (_member01..); each frame is rebuilt under the standard
    variable names. Rows where the ensemble has no data (deep past) are dropped
    so they cannot mask the ERA5 history when stitched."""
    h = get(GEFS_URL.format(lat=LAT, lon=LON))["hourly"]
    idx = pd.to_datetime(h["time"], utc=True)
    base_vars = VARS_ENS.split(",")
    out = {}
    for suffix in [""] + [f"_member{i:02d}" for i in range(1, 31)]:
        cols = {v: h.get(v + suffix) for v in base_vars}
        if any(c is None for c in cols.values()):
            continue
        df = pd.DataFrame(cols, index=idx).dropna(subset=["temperature_2m"])
        out["GEFS control" if suffix == "" else f"GEFS {suffix[-2:]}"] = df
    return out


def get(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)


def frame(payload):
    h = payload["hourly"]
    df = pd.DataFrame(h)
    df.index = pd.to_datetime(df.pop("time"), utc=True)
    return df


if __name__ == "__main__":
    end = pd.Timestamp.now("UTC").strftime("%Y-%m-%d")
    hist = frame(get(ARCHIVE.format(lat=LAT, lon=LON, end=end)))
    hist.to_csv("data/weather.csv")
    print(f"weather history: {len(hist)} hours, {hist.index[0]:%Y-%m-%d} to {hist.index[-1]:%Y-%m-%d}")

    fc = frame(get(FORECAST.format(lat=LAT, lon=LON)))
    fc.to_csv("data/weather_forecast.csv")
    print(f"weather forecast: {len(fc)} hours out to {fc.index[-1]:%Y-%m-%d}")
