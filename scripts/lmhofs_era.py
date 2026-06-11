"""Era-parallel driver for fetch_lmhofs.day_series: fetch one date span into
its own csv so several spans can run concurrently, then scripts/lmhofs_merge.py
combines them into data/lmhofs.csv. Resumable per output file.

usage: python3 scripts/lmhofs_era.py 2019-09-01 2021-11-30 data/lmhofs_a.csv"""

import sys
import pathlib

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import fetch_lmhofs as fl

start, end, path = pd.Timestamp(sys.argv[1], tz="UTC"), pd.Timestamp(sys.argv[2], tz="UTC"), sys.argv[3]

try:
    cur = pd.read_csv(path, index_col=0, parse_dates=True)
    cur.index = pd.to_datetime(cur.index, utc=True)
    have = set(cur.index.normalize().unique())
except FileNotFoundError:
    cur = pd.DataFrame(columns=[fl.COL])
    cur.index = pd.DatetimeIndex([], tz="UTC")
    have = set()

days = [d for d in pd.date_range(start, end, freq="D") if d.month in fl.SEASON]
pieces = [cur] if len(cur) else []
fetched = 0


def flush():
    out = pd.concat(pieces)
    out.index = pd.to_datetime(out.index, utc=True)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.to_csv(path)


for day in days:
    if day in have:
        continue
    s = fl.day_series(day)
    if len(s):
        pieces.append(s.to_frame())
    fetched += 1
    if fetched % 25 == 0 and pieces:
        flush()
        print(f"  {path}: through {day:%Y-%m-%d} ({fetched} days)", flush=True)
if pieces:
    flush()
print(f"done {path}: {start:%Y-%m-%d}..{end:%Y-%m-%d}")
