"""SCAFFOLD (not yet live): pull Google DeepMind's WeatherNext 2 ensemble as an
extra weather source for the perfect-prog water-temp model.

WHY: the day-7 band has two halves. The subsurface streams (satellite + LMHOFS)
fixed the LAKE side (upwelling tail). The other half is WEATHER-forecast spread,
and that is what WeatherNext attacks: a 64-member, 15-day, 0.25deg ML ensemble
(the GraphCast/GenCast/FGN lineage, competitive with or beating ECMWF ENS). More
members + longer horizon than today's 34-member, 8-day Open-Meteo blend ->
potentially sharper, better-calibrated weather uncertainty at long lead.

STATUS: ACCESS-GATED. As of 2026-06-14 the BigQuery dataset
`gcp-public-data-weathernext` returns "Not found" (no access), and Earth Engine
is not registered on this machine. To unlock:
  1. Fill the WeatherNext Data Request form (linked from the Earth Engine catalog
     page: projects/gcp-public-data-weathernext/assets/weathernext_2_0_0).
  2. Either: `pip install earthengine-api` + `earthengine authenticate` (EE path),
     or grant the project BigQuery access to the dataset (BQ path; we already
     have the `bq` CLI authed as project nodal-broker-475823-k9).
  3. Run this module to verify the pull, then wire frame() into publish.py's
     ensemble loop (members_wx) alongside the GEFS/ECMWF/ICON/GEM members.

KNOWN LIMITATION (confirmed from the catalog band list): WeatherNext publishes
temperature, wind (u/v), humidity, pressure, SST, etc. -- but NOT shortwave
radiation or wind gusts, which featuresq's fut_solar and fut_gust need. So
WeatherNext can supply fut_t2m / fut_u / fut_v / fut_wspd / fut_dewdep, but
fut_solar and fut_gust would be NaN for its members (HGB tolerates NaN). Its SST
is a global atmosphere-model field, NOT Great-Lakes-resolved -- the lake stays
LMHOFS's job; use WeatherNext only for the atmospheric forcing + ensemble spread.
"""

import sys

import numpy as np
import pandas as pd

# NDBC 45174, the Wilmette buoy (the model's point)
LAT, LON = 42.10, -87.70
EE_ASSET = "projects/gcp-public-data-weathernext/assets/weathernext_2_0_0"
# WeatherNext band -> the Open-Meteo column names featuresq.future_generic expects.
# (u/v are reconstructed from speed+direction in features.build; here we hand the
#  ensemble member frames the same generic columns publish.py feeds the model.)
BAND_MAP = {
    "2m_temperature": "temperature_2m",            # Kelvin -> convert to C
    "10m_u_component_of_wind": "u10",
    "10m_v_component_of_wind": "v10",
    "2m_dewpoint_temperature": "dew_point_2m",     # Kelvin -> C
    "mean_sea_level_pressure": "pressure_msl",
    # no shortwave radiation, no wind gusts in WeatherNext -> fut_solar/fut_gust stay NaN
}


def _require_ee():
    try:
        import ee  # noqa: F401
        return ee
    except ImportError:
        sys.exit("earthengine-api not installed. See module docstring to set up access:\n"
                 "  pip install earthengine-api && earthengine authenticate")


def members(init_utc, lead_hours=range(0, 24 * 15 + 1, 6)):
    """Return {member_id: DataFrame} of the WeatherNext ensemble at the Wilmette
    cell for one init time, columns matching fetch_weather's frame() so each
    member can drop into publish.py's perfect-prog loop. NOT YET RUNNABLE -- needs
    access (see docstring); the EE query shape below is the intended starting
    point to verify against the real schema on first access."""
    ee = _require_ee()
    ee.Initialize()
    pt = ee.Geometry.Point([LON, LAT])
    init = ee.Filter.date(init_utc, pd.Timestamp(init_utc) + pd.Timedelta(hours=1))
    coll = ee.ImageCollection(EE_ASSET).filter(init)
    # TODO on first access: confirm property names (ensemble_member, forecast_hour),
    # band names in BAND_MAP, units (Kelvin for temps), and the point-sampling call
    # (getRegion vs sampleRegions). Reduce coll -> per (member, forecast_hour) the
    # BAND_MAP bands at `pt`, then pivot into one hourly frame per member:
    raise NotImplementedError(
        "WeatherNext access not yet provisioned; see fetch_weathernext.py docstring. "
        "Once access lands, sample BAND_MAP bands at the Wilmette point across "
        "ensemble_member x forecast_hour and return frames shaped like fetch_weather.frame().")


def frame(member_df):
    """Map a raw member frame (BAND_MAP columns, 6-hourly) onto the generic hourly
    weather columns featuresq expects, interpolating 6h -> 1h. Solar/gust -> NaN."""
    out = pd.DataFrame(index=member_df.index)
    out["temperature_2m"] = member_df["temperature_2m"] - 273.15
    out["dew_point_2m"] = member_df["dew_point_2m"] - 273.15
    out["u"] = member_df["u10"]
    out["v"] = member_df["v10"]
    out["wind_speed_10m"] = np.hypot(member_df["u10"], member_df["v10"])
    out["wind_gusts_10m"] = np.nan          # not in WeatherNext
    out["shortwave_radiation"] = np.nan     # not in WeatherNext
    return out.resample("1h").interpolate()


if __name__ == "__main__":
    print(__doc__)
    print("This is a scaffold. Provision access, then implement members() against the real schema.")
