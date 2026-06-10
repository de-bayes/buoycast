"""Fetch hourly weather over the buoy site: ERA5 reanalysis for the training
years (archive API) and the GFS/HRRR forecast for the next 8 days (forecast
API). Same variables and units from both, so train and inference match.
Writes data/weather.csv (history) and data/weather_forecast.csv."""

import json
import urllib.request

import pandas as pd

LAT, LON = 42.05, -87.66
VARS = "temperature_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,shortwave_radiation,cloud_cover"

ARCHIVE = (
    "https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
    "&start_date=2021-05-01&end_date={end}&hourly=" + VARS +
    "&wind_speed_unit=ms&timezone=UTC"
)
FORECAST = (
    "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
    "&hourly=" + VARS + "&wind_speed_unit=ms&forecast_days=8&timezone=UTC"
)


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
