"""Fetch the City of Chicago beach water-quality sensors (Socrata qmqz-2xku):
hourly nearshore water temperature on the same shelf as the buoy, 2013 to
present, same-day latency. Sensors deploy roughly April to October, so the
off-season is NaN by construction. Writes data/chibeach.csv, hourly UTC,
one column per beach."""

import json
import sys
import time
import urllib.parse
import urllib.request

import pandas as pd

URL = "https://data.cityofchicago.org/resource/qmqz-2xku.json"
FIELDS = "beach_name,measurement_timestamp,water_temperature"
PATH = "data/chibeach.csv"
SLUG = {"Ohio Street Beach": "beach_ohio", "Montrose Beach": "beach_montrose",
        "Osterman Beach": "beach_osterman", "Calumet Beach": "beach_calumet",
        "Rainbow Beach": "beach_rainbow", "63rd Street Beach": "beach_63rd"}


def fetch_all(since=None):
    rows, offset, limit = [], 0, 50000
    where = f"&$where=measurement_timestamp>'{since}'" if since else ""
    while True:
        q = (f"{URL}?$select={urllib.parse.quote(FIELDS)}&$order=measurement_timestamp"
             f"&$limit={limit}&$offset={offset}" + urllib.parse.quote(where, safe="&$=>'"))
        with urllib.request.urlopen(q, timeout=120) as r:
            chunk = json.load(r)
        rows.extend(chunk)
        print(f"  {len(rows)} records ...")
        if len(chunk) < limit:
            return rows
        offset += limit
        time.sleep(0.5)


def to_frame(rows):
    df = pd.DataFrame(rows).dropna()
    df["water_temperature"] = pd.to_numeric(df["water_temperature"], errors="coerce")
    # sensor glitches: occasional 0.0 readings and impossible spikes
    df = df[(df["water_temperature"] > 0.5) & (df["water_temperature"] < 35)]
    ts = pd.to_datetime(df["measurement_timestamp"])
    df["t"] = ts.dt.tz_localize("America/Chicago", ambiguous="NaT",
                                nonexistent="NaT").dt.tz_convert("UTC")
    df = df.dropna(subset=["t"])
    df["col"] = df["beach_name"].map(SLUG)
    df = df.dropna(subset=["col"])
    wide = df.pivot_table(index="t", columns="col", values="water_temperature")
    return wide.resample("1h").mean()


def main(mode):
    if mode == "backfill":
        out = to_frame(fetch_all())
    else:
        since = (pd.Timestamp.now() - pd.Timedelta(days=14)).strftime("%Y-%m-%dT00:00:00")
        fresh = to_frame(fetch_all(since=since))
        cur = pd.read_csv(PATH, index_col=0, parse_dates=True)
        out = pd.concat([cur, fresh])
        out = out[~out.index.duplicated(keep="last")].sort_index()
    out.to_csv(PATH)
    nn = out.notna().sum()
    print(f"wrote {PATH}: {len(out)} hours, {out.index.min()} to {out.index.max()}")
    print(nn.to_string())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "update")
