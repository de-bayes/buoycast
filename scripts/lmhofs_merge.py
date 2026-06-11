"""Merge the era-parallel LMHOFS files (data/lmhofs_*.csv) into the single
data/lmhofs.csv the feature pipeline reads, on an explicit hourly grid."""

import glob
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

parts = sorted(glob.glob("data/lmhofs_[abc]*.csv"))
frames = []
for p in parts:
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    frames.append(df)
    print(f"  {p}: {df['lmhofs_sst'].notna().sum()} hours")
out = pd.concat(frames)
out = out[~out.index.duplicated(keep="last")].sort_index().asfreq("1h")
out.to_csv("data/lmhofs.csv")
by_year = out["lmhofs_sst"].notna().groupby(out.index.year).sum()
print(f"wrote data/lmhofs.csv: {out['lmhofs_sst'].notna().sum()} hours total")
print(by_year.to_string())
