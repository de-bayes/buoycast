# buoycast

ML forecasts of nearshore water temperature (and, honestly, not wave height) from the Wilmette buoy, NDBC station 45174, a few miles up the shore from the Evanston beaches.

## How it works

1. `python3 fetch.py` downloads the buoy's 2021-2025 historical standard-met archives plus the 45-day realtime feed from NDBC (open data, no key) and writes a merged hourly series to `data/buoy.csv`. The buoy is seasonal (roughly May to November), so winters are gaps.
2. `python3 train.py` builds lag/delta/rolling-wind/seasonal features and trains a `HistGradientBoostingRegressor` per target and horizon (+3, +6, +12, +24 h), holding out the most recent three in-season weeks. Every model is scored against persistence (forecast = current value), the baseline any honest nowcast must beat.
3. `python3 forecast.py` pulls the latest observations, runs the models, prints a readable forecast with holdout error bars, and writes `forecast.json`.

## Current skill (holdout MAE vs persistence)

| Target | +3h | +6h | +12h | +24h |
| --- | --- | --- | --- | --- |
| Water temp (C) | 0.19 vs 0.23 | 0.32 vs 0.41 | 0.48 vs 0.60 | 0.57 vs 0.69 |
| Wave height (m) | 0.10 vs 0.07 | 0.15 vs 0.11 | 0.21 vs 0.16 | 0.29 vs 0.24 |

Water temperature beats persistence at every horizon (the rolling wind-vector features carry the upwelling signal: sustained alongshore wind pushes warm surface water offshore and cold water up). Wave height loses to persistence at every horizon, which is physically expected: waves on a 12-mile fetch are driven by wind that has not happened yet, and nothing in the buoy's own past predicts it. The forecast output flags those rows. The fix, if wanted, is feeding Open-Meteo forecast winds in as future covariates.

## Notes

- Wilmette buoy is also on the GLOS Seagull platform; NDBC text feeds were chosen for zero-auth simplicity.
- Sensors report every 10 minutes in season; everything here works on hourly means.
- Lifeguard-relevant: the upwelling events this model is good at are the ones that drop swim areas 10F overnight.
