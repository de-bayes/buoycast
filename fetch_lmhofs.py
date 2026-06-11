"""Fetch LMHOFS (NOAA Lake Michigan-Huron Operational Forecast System) surface
water temperature at the Wilmette buoy (station 45174), a named station in the
LMHOFS stations files. Three eras feed the same hourly UTC series:

  NCEI THREDDS  2019-09 .. 2023-11  (OpenDAP DAP ASCII, no netCDF lib)
  AWS S3        2024-03 .. present  (download stations.nowcast.nc, read netCDF4)
  CO-OPS THREDDS  rolling ~30 days  (DAP ASCII; live forecast + recent nowcasts)

Each daily cycle (00/06/12/18z) nowcast is a 61-step 6-minute series over the 6 h
up to cycle time; concatenating the four cycles and keeping top-of-hour values
gives the hourly history. The buoy is seasonal, so only April-November months are
fetched (2023-12 .. 2024-02 is an expected gap). backfill() writes data/lmhofs.csv
(DatetimeIndex hourly UTC, one column lmhofs_sst, degrees C) and is resumable per
day. live() returns the latest CO-OPS forecast (1201 steps of 360 s = 120 h) plus
the preceding nowcasts as an hourly Series.

temp is dimensioned (time, siglay, station); siglay index 0 is the surface. The
station index of 45174 is NOT stable across years (47 stations in 2019, 48 now),
so name_station is read per file and the index found by matching "45174". The
time units attr differs by era (old "days since 2018-01-01", new "seconds since
2018-01-01 00:00:00"), so it is read per file."""

import os
import re
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request

import pandas as pd

# NCEI publishes IPv6 (AAAA) records first; on an IPv4-only route urllib stalls
# for minutes on the dead v6 address per request (curl avoids this via Happy
# Eyeballs). Prefer IPv4 so the ~4800-request backfill is feasible; fall back to
# the full list if a host has no A record.
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_first(host, *args, **kwargs):
    res = _orig_getaddrinfo(host, *args, **kwargs)
    return [r for r in res if r[0] == socket.AF_INET] or res


socket.getaddrinfo = _ipv4_first

STATION = "45174"
PATH = "data/lmhofs.csv"
COL = "lmhofs_sst"
CYCLES = ("00", "06", "12", "18")
EPOCH = pd.Timestamp("2018-01-01", tz="UTC")  # time-units reference for all eras

NCEI = ("https://www.ncei.noaa.gov/thredds/dodsC/model-lmhofs-files/{y}/{m:02d}/"
        "nos.lmhofs.stations.nowcast.{y}{m:02d}{d:02d}.t{cyc}z.nc")
AWS = ("https://noaa-nos-ofs-pds.s3.amazonaws.com/lmhofs/netcdf/{y}/{m:02d}/{d:02d}/"
       "lmhofs.t{cyc}z.{y}{m:02d}{d:02d}.stations.nowcast.nc")
# the 2024 transition year used a flat month-folder layout with the old NCEI
# style names (and some 2024 months are simply absent from the bucket)
AWS_FLAT = ("https://noaa-nos-ofs-pds.s3.amazonaws.com/lmhofs/netcdf/{y}{m:02d}/"
            "nos.lmhofs.stations.nowcast.{y}{m:02d}{d:02d}.t{cyc}z.nc")
COOPS = ("https://opendap.co-ops.nos.noaa.gov/thredds/dodsC/NOAA/LMHOFS/MODELS/"
         "{y}/{m:02d}/{d:02d}/lmhofs.t{cyc}z.{y}{m:02d}{d:02d}.stations.{kind}.nc")

# OpenDAP is slow to spin up (NCEI especially), so timeouts are generous.
DAP_TIMEOUT = 300
SEASON = range(4, 12)  # April..November, the buoy's deployment window


# ---- DAP ASCII helpers (NCEI + CO-OPS) -------------------------------------

def _dap(url, timeout=DAP_TIMEOUT):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def time_units_days(url):
    """True if the file's time units are 'days since ...', else seconds."""
    return "days since" in _dap(url + ".das")


def station_index(url):
    """Index of STATION in name_station, read from the DAP ASCII listing."""
    text = _dap(url + ".ascii?name_station")
    names = re.findall(r'"\s*([0-9A-Za-z]+)\s*"', text)
    return names.index(STATION)


def _parse_temp_ascii(text):
    """Surface temps from a temp[t][0][s] DAP ASCII response, in time order."""
    vals = re.findall(r"^\[\d+\]\[\d+\],\s*([-\d.eE+]+)\s*$", text, re.M)
    return [float(v) for v in vals]


def _to_time(tv, days_units):
    """Raw time value -> UTC timestamp, rounded to the nearest minute. The
    'days since' era stores 6-min steps as day fractions whose float rounding
    lands a few seconds off the minute, so rounding is needed for the
    top-of-hour filter to catch them."""
    secs = tv * 86400 if days_units else tv
    return (EPOCH + pd.Timedelta(seconds=secs)).round("1min")


def dap_cycle(url, n_time, idx, days_units):
    """Hourly-resolvable (timestamp -> degC) dict for one cycle via DAP ASCII.
    n_time steps of 360 s; surface siglay 0; station column idx. temp and time
    ride one request (DAP serves projections in order, temp then time)."""
    enc = ("temp%5B0:1:{n}%5D%5B0:1:0%5D%5B{i}:1:{i}%5D,time%5B0:1:{n}%5D"
           .format(n=n_time - 1, i=idx))
    text = _dap(url + ".ascii?" + enc)
    temps = _parse_temp_ascii(text)
    # the data section prints "time[N]" at line start then one comma-separated
    # row; servers order sections by file layout, not projection order
    m = re.search(r"^time\[\d+\]\s*\n([^\n]+)", text, re.M)
    tvals = [float(x) for x in m.group(1).split(",")]
    out = {}
    for tv, tp in zip(tvals, temps):
        out[_to_time(tv, days_units)] = tp
    return out


# ---- AWS netCDF helpers -----------------------------------------------------

def aws_cycle(url):
    """(timestamp -> degC) dict for one cycle from a downloaded stations.nc."""
    import netCDF4
    fd, path = tempfile.mkstemp(suffix=".nc")
    os.close(fd)
    try:
        # urlretrieve has no timeout and can hang forever on a half-closed
        # connection; stream through urlopen instead. S3 sheds connections
        # under load and a dead one should fail fast, the retry will land.
        with urllib.request.urlopen(url, timeout=25) as r, open(path, "wb") as fh:
            fh.write(r.read())
        ds = netCDF4.Dataset(path)
        names = [netCDF4.chartostring(ds.variables["name_station"][i]).item().strip()
                 for i in range(ds.dimensions["station"].size)]
        idx = names.index(STATION)
        days_units = "days since" in ds.variables["time"].units
        tvals = ds.variables["time"][:]
        temps = ds.variables["temp"][:, 0, idx]
        ds.close()
    finally:
        os.remove(path)
    out = {}
    for tv, tp in zip(tvals.tolist(), temps.tolist()):
        out[_to_time(tv, days_units)] = float(tp)
    return out


# ---- per-day collection -----------------------------------------------------

_META = {}  # (year, month) -> (station idx, days_units); shifts only across eras


def day_series(day):
    """Hourly UTC Series of surface temp for one calendar day, by stitching all
    four cycles' nowcasts from whichever era serves that day. Empty Series if no
    files are reachable (warned)."""
    y, m, d = day.year, day.month, day.day
    use_aws = day >= pd.Timestamp("2024-03-01", tz="UTC")
    merged = {}
    idx, days_units = _META.get((y, m), (None, None))
    def aws_either(cyc):
        try:
            return aws_cycle(AWS.format(y=y, m=m, d=d, cyc=cyc))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            return aws_cycle(AWS_FLAT.format(y=y, m=m, d=d, cyc=cyc))

    for cyc in CYCLES:
        try:
            if use_aws:
                merged.update(aws_either(cyc))
            else:
                url = NCEI.format(y=y, m=m, d=d, cyc=cyc)
                if idx is None:
                    idx = station_index(url)
                    days_units = time_units_days(url)
                    _META[(y, m)] = (idx, days_units)
                try:
                    merged.update(dap_cycle(url, 61, idx, days_units))
                except (ValueError, IndexError):
                    # station set or units may have shifted; re-read this file
                    idx = station_index(url)
                    days_units = time_units_days(url)
                    _META[(y, m)] = (idx, days_units)
                    merged.update(dap_cycle(url, 61, idx, days_units))
        except Exception as e:  # missing cycle or transient failure: one retry
            time.sleep(1.0)
            try:
                if use_aws:
                    merged.update(aws_either(cyc))
                else:
                    url = NCEI.format(y=y, m=m, d=d, cyc=cyc)
                    if idx is None:
                        idx = station_index(url)
                        days_units = time_units_days(url)
                    merged.update(dap_cycle(url, 61, idx, days_units))
            except Exception:
                print(f"  warn {day:%Y-%m-%d} t{cyc}z: {type(e).__name__} {e}")
        if not use_aws:
            time.sleep(0.15)  # be polite to NCEI OpenDAP
    if not merged:
        return pd.Series(dtype=float, name=COL)
    s = pd.Series(merged, name=COL).sort_index()
    # keep top-of-hour (minute == 0) samples; the 6-min series lands on them
    s = s[s.index.minute == 0]
    s = s[~s.index.duplicated(keep="last")]
    return s


# ---- backfill ---------------------------------------------------------------

def backfill():
    """Build/extend data/lmhofs.csv over the seasonal months across all eras.
    Resumable: days already present are skipped; the csv is flushed every ~25
    new days so progress survives interruption."""
    try:
        cur = pd.read_csv(PATH, index_col=0, parse_dates=True)
        cur.index = pd.to_datetime(cur.index, utc=True)
    except FileNotFoundError:
        cur = pd.DataFrame(columns=[COL])
        cur.index = pd.DatetimeIndex([], tz="UTC")
    have_days = set(cur.index.normalize().unique())

    start = pd.Timestamp("2019-09-01", tz="UTC")
    end = pd.Timestamp.now("UTC").normalize() - pd.Timedelta(days=1)
    all_days = [d for d in pd.date_range(start, end, freq="D")
                if d.month in SEASON]

    pieces = [cur] if len(cur) else []
    done = 0
    fetched = 0
    for day in all_days:
        done += 1
        if day in have_days:
            continue
        # the 2023-12 .. 2024-02 winter gap and pre-deployment days yield nothing
        s = day_series(day)
        if len(s):
            pieces.append(s.to_frame())
        fetched += 1
        if fetched % 50 == 0:
            print(f"  {day:%Y-%m-%d}: {fetched} days fetched, {done}/{len(all_days)} scanned")
        if fetched % 25 == 0 and pieces:
            _flush(pieces)
    _flush(pieces)
    out = pd.read_csv(PATH, index_col=0, parse_dates=True)
    out.index = pd.to_datetime(out.index, utc=True)
    print(f"wrote {PATH}: {out[COL].notna().sum()} hours, "
          f"{out.index.min()} to {out.index.max()}")


def _flush(pieces):
    out = pd.concat(pieces)
    out.index = pd.to_datetime(out.index, utc=True)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out.asfreq("1h")  # explicit hourly grid, gaps as NaN
    out.to_csv(PATH)


# ---- live -------------------------------------------------------------------

def _coops_url(day, cyc, kind):
    return COOPS.format(y=day.year, m=day.month, d=day.day, cyc=cyc, kind=kind)


def _latest_forecast():
    """(forecast url, day, cyc) for the newest reachable CO-OPS forecast cycle,
    scanning today then yesterday across cycles newest-first."""
    now = pd.Timestamp.now("UTC")
    for back in (0, 1):
        day = (now - pd.Timedelta(days=back)).normalize()
        for cyc in reversed(CYCLES):
            url = _coops_url(day, cyc, "forecast")
            try:
                if "days since" in _dap(url + ".das", timeout=60) or True:
                    return url, day, cyc
            except Exception:
                continue
    raise RuntimeError("no reachable CO-OPS forecast cycle found")


def live():
    """Hourly UTC Series spanning roughly (now-48h) .. (cycle+120h): the latest
    CO-OPS forecast plus the preceding nowcast cycles for the recent past."""
    furl, day, cyc = _latest_forecast()
    idx = station_index(furl)
    days_units = time_units_days(furl)
    series = dap_cycle(furl, 1201, idx, days_units)  # 120 h forecast

    # preceding ~48 h: the nowcast of this cycle and the prior eight cycles
    cyc_time = day + pd.Timedelta(hours=int(cyc))
    for back in range(0, 9):
        ct = cyc_time - pd.Timedelta(hours=6 * back)
        nurl = _coops_url(ct.normalize(), f"{ct.hour:02d}", "nowcast")
        try:
            series.update(dap_cycle(nurl, 61, idx, days_units))
        except Exception:
            continue

    s = pd.Series(series, name=COL).sort_index()
    s = s[s.index.minute == 0]
    s = s[~s.index.duplicated(keep="last")]
    return s.asfreq("1h")


def _print_live(s):
    now = pd.Timestamp.now("UTC").floor("h")

    def at(ts):
        ts = s.index[s.index.get_indexer([ts], method="nearest")[0]]
        return s.loc[ts]
    print(f"live: {len(s)} hours, {s.index.min()} .. {s.index.max()}")
    print(f"  now   {at(now):.2f}C")
    print(f"  +24h  {at(now + pd.Timedelta(hours=24)):.2f}C")
    print(f"  +72h  {at(now + pd.Timedelta(hours=72)):.2f}C")
    print(f"  +120h {at(now + pd.Timedelta(hours=120)):.2f}C")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "live"
    if mode == "backfill":
        backfill()
    else:
        _print_live(live())
