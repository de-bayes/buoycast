"""Download Wilmette buoy history (2016-2025) plus the 45-day realtime feed
and write the merged hourly series to data/buoy.csv. Also pulls the open-lake
neighbor buoy (southern Lake Michigan), whose water temp and waves lead the
nearshore Wilmette site, to data/buoy_neighbor.csv."""

import buoy
import featuresq

frames = buoy.fetch_history(range(2016, 2026))
print("  realtime: ", end="")
frames.append(buoy.fetch_realtime())
print("ok")

hourly = buoy.to_hourly(frames)
hourly.to_csv("data/buoy.csv")
valid = hourly["WTMP"].notna().sum()
print(f"wrote data/buoy.csv: {len(hourly)} hourly rows, {valid} with water temp "
      f"({hourly.index[0]:%Y-%m-%d} to {hourly.index[-1]:%Y-%m-%d})")

nbr = featuresq.NEIGHBOR_STATION
print(f"open-lake neighbor {nbr}:")
nframes = buoy.fetch_history(range(2016, 2026), station=nbr)
print("  realtime: ", end="")
try:
    nframes.append(buoy.fetch_realtime(station=nbr))
    print("ok")
except Exception as e:
    print(f"skipped ({e})")
nhourly = buoy.to_hourly(nframes)
nhourly.to_csv(featuresq.NEIGHBOR_PATH)
nvalid = nhourly["WTMP"].notna().sum()
print(f"wrote {featuresq.NEIGHBOR_PATH}: {len(nhourly)} hourly rows, {nvalid} with water temp "
      f"({nhourly.index[0]:%Y-%m-%d} to {nhourly.index[-1]:%Y-%m-%d})")
