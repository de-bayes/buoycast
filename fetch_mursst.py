"""Fetch daily satellite lake-surface temperature around the buoy from NASA
MUR SST (0.01 deg global L4 analysis, 2002-present, ~1 day latency) via the
NOAA CoastWatch PFEG ERDDAP. Two products per day: a 9-point eastward
transect from the buoy pixel into open water (the cross-shore structure that
upwelling rearranges) and a southern-basin mean. Writes data/mursst.csv with
a daily date index; the as-of join to hourly happens in featuresq.

GLERL's own GLSEA (1.4 km, lakes-native) would be sharper nearshore, but its
data services were unreachable when tested; MUR is the reliable mirror."""

import io
import socket
import sys
import time
import urllib.request

import pandas as pd

# this network's IPv6 route to NOAA is dead; urllib tries it first and hangs
# for the whole connect timeout, so prefer IPv4 (same fix as fetch_lmhofs)
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_first(host, *args, **kwargs):
    res = _orig_getaddrinfo(host, *args, **kwargs)
    return [r for r in res if r[0] == socket.AF_INET] or res


socket.getaddrinfo = _ipv4_first

BASE = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41.csv"
LAT = 42.13
# 9 pixels eastward from the buoy at 0.1 deg (~8.3 km) spacing: -87.66 .. -86.86
TRANSECT = "%5B({t0}):({t1})%5D%5B(42.13):(42.13)%5D%5B(-87.66):10:(-86.80)%5D"
# strided box over the southern basin west half, 7 x 21 pixels at ~5 km spacing
BOX = "%5B({t0}):({t1})%5D%5B(42.0):5:(42.3)%5D%5B(-87.8):5:(-86.8)%5D"
STAMP = "T09:00:00Z"  # MUR nominal daily analysis time
PATH = "data/mursst.csv"


def get_csv(query):
    url = BASE + "?analysed_sst" + query
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=300) as r:
                raw = r.read().decode()
            return pd.read_csv(io.StringIO(raw), skiprows=[1])  # row 1 is units
        except Exception as e:
            if attempt == 2:
                raise
            print(f"  retry after {type(e).__name__}: {e}")
            time.sleep(10)


def fetch_range(d0, d1):
    """One transect + one box request covering [d0, d1]; returns a daily frame."""
    span = dict(t0=d0 + STAMP, t1=d1 + STAMP)
    tr = get_csv(TRANSECT.format(**span))
    bx = get_csv(BOX.format(**span))
    for df in (tr, bx):
        df["date"] = pd.to_datetime(df["time"]).dt.date

    wide = tr.pivot_table(index="date", columns="longitude", values="analysed_sst")
    wide.columns = [f"sat_x{i}" for i in range(len(wide.columns))]  # x0=buoy .. x8=66km east
    wide["sat_basin"] = bx.groupby("date")["analysed_sst"].mean()
    return wide


def backfill(start_year=2016):
    have = set()
    try:
        cur = pd.read_csv(PATH, index_col=0, parse_dates=True)
        have = {y for y in cur.index.year.unique()
                if (cur.index.year == y).sum() >= 360}  # only skip complete years
    except FileNotFoundError:
        cur = None
    frames = [] if cur is None else [cur]
    this_year = pd.Timestamp.now("UTC").year
    for year in range(start_year, this_year + 1):
        if year in have and year != this_year:
            continue
        end = f"{year}-12-31" if year != this_year else (
            pd.Timestamp.now("UTC") - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"{year}: fetching transect + basin box ...")
        frames.append(fetch_range(f"{year}-01-01", end))
        time.sleep(2)
    out = pd.concat(frames)
    out.index = pd.to_datetime(out.index)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.to_csv(PATH)
    print(f"wrote {PATH}: {len(out)} days, {out.index.min():%Y-%m-%d} to {out.index.max():%Y-%m-%d}")


def update(days=14):
    """Live refresh: upsert the trailing two weeks."""
    d1 = (pd.Timestamp.now("UTC") - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    d0 = (pd.Timestamp.now("UTC") - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    fresh = fetch_range(d0, d1)
    fresh.index = pd.to_datetime(fresh.index)
    try:
        cur = pd.read_csv(PATH, index_col=0, parse_dates=True)
        out = pd.concat([cur, fresh])
        out = out[~out.index.duplicated(keep="last")].sort_index()
    except FileNotFoundError:
        out = fresh
    out.to_csv(PATH)
    print(f"updated {PATH} through {out.index.max():%Y-%m-%d} "
          f"(buoy pixel {out['sat_x0'].iloc[-1]:.2f}C, basin {out['sat_basin'].iloc[-1]:.2f}C)")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "update"
    backfill() if mode == "backfill" else update()
