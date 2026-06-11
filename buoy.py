"""Shared NDBC plumbing for station 45174 (Wilmette buoy): download, parse,
and resample standard meteorological files into a clean hourly frame."""

import io
import urllib.request

import pandas as pd

STATION = "45174"
HIST_URL = (
    "https://www.ndbc.noaa.gov/view_text_file.php"
    "?filename={station}h{year}.txt.gz&dir=data/historical/stdmet/"
)
REALTIME_URL = "https://www.ndbc.noaa.gov/data/realtime2/{station}.txt"

KEEP = ["WDIR", "WSPD", "GST", "WVHT", "PRES", "ATMP", "WTMP"]
# sentinel thresholds per column; NDBC uses 99/999/9999 for missing
MISSING_AT = {"WDIR": 998, "WSPD": 98, "GST": 98, "WVHT": 98, "PRES": 9998, "ATMP": 98, "WTMP": 98}


def read_stdmet(text):
    lines = text.splitlines()
    names = lines[0].lstrip("#").split()
    body = "\n".join(l for l in lines[1:] if not l.startswith("#"))
    df = pd.read_csv(io.StringIO(body), sep=r"\s+", names=names, na_values=["MM"])
    # date columns are YY MM DD hh mm (YYYY since 1999)
    ts = pd.to_datetime(
        dict(
            year=df[names[0]], month=df[names[1]], day=df[names[2]],
            hour=df[names[3]], minute=df[names[4]],
        ),
        utc=True,
    )
    out = pd.DataFrame(index=pd.DatetimeIndex(ts))
    for col in KEEP:
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce")
            out[col] = vals.where(vals < MISSING_AT[col]).to_numpy()
    return out.sort_index()


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def fetch_history(years, station=STATION):
    frames = []
    for y in years:
        try:
            frames.append(read_stdmet(fetch(HIST_URL.format(station=station, year=y))))
            print(f"  {y}: ok")
        except Exception as e:  # season gaps and missing years are expected
            print(f"  {y}: skipped ({e})")
    return frames


def fetch_realtime(station=STATION):
    return read_stdmet(fetch(REALTIME_URL.format(station=station)))


def to_hourly(frames):
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.resample("1h").mean()
