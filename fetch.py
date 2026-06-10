"""Download Wilmette buoy history (2021-2025) plus the 45-day realtime feed
and write the merged hourly series to data/buoy.csv."""

import buoy

frames = buoy.fetch_history(range(2021, 2026))
print("  realtime: ", end="")
frames.append(buoy.fetch_realtime())
print("ok")

hourly = buoy.to_hourly(frames)
hourly.to_csv("data/buoy.csv")
valid = hourly["WTMP"].notna().sum()
print(f"wrote data/buoy.csv: {len(hourly)} hourly rows, {valid} with water temp "
      f"({hourly.index[0]:%Y-%m-%d} to {hourly.index[-1]:%Y-%m-%d})")
