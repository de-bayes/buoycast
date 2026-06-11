"""Render the site2 hero visuals from the real MUR satellite SST grid
(data/mur_grid.csv): a full-bleed thermal map of southern Lake Michigan on
near-black, plus a tight crop around the buoy for the locator panel."""

import pathlib
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from scipy import ndimage

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

BUOY_LAT, BUOY_LON = 42.135, -87.655
BG = "#060709"

df = pd.read_csv("data/mur_grid.csv")
lats = np.sort(df.latitude.unique())
lons = np.sort(df.longitude.unique())
grid = df.pivot_table(index="latitude", columns="longitude",
                      values="analysed_sst").reindex(index=lats, columns=lons).to_numpy()

# upsample x4 with smooth interpolation; keep the land mask crisp
mask = np.isnan(grid)
filled = np.where(mask, np.nanmean(grid), grid)
big = ndimage.zoom(ndimage.gaussian_filter(filled, 1.0), 4, order=3)
bigmask = ndimage.zoom(mask.astype(float), 4, order=1) > 0.45

# thermal palette in the WeatherNext register: deep blue -> teal -> green ->
# yellow, vivid against black
cmap = LinearSegmentedColormap.from_list("lake", [
    (0.00, "#0b1c66"), (0.22, "#0e4fa8"), (0.45, "#0e93b4"),
    (0.62, "#27c08b"), (0.80, "#a8d934"), (1.00, "#f8e24d")])

field = np.ma.masked_array(big, bigmask)
vmin, vmax = np.nanpercentile(grid, 2), np.nanpercentile(grid, 99.5)

extent = [lons.min(), lons.max(), lats.min(), lats.max()]

def render(path, ext, figsize, mark=True, contours=True, dpi=200):
    fig, ax = plt.subplots(figsize=figsize, facecolor=BG)
    ax.set_facecolor(BG)
    ax.imshow(field, origin="lower", extent=extent, cmap=cmap,
              vmin=vmin, vmax=vmax, interpolation="bilinear", aspect="auto")
    if contours:
        ax.contour(np.linspace(extent[0], extent[1], big.shape[1]),
                   np.linspace(extent[2], extent[3], big.shape[0]),
                   np.where(bigmask, np.nan, big),
                   levels=10, colors="white", linewidths=0.35, alpha=0.18)
    if mark:
        ax.plot(BUOY_LON, BUOY_LAT, "o", ms=5, mfc="white", mec="white")
        ax.plot(BUOY_LON, BUOY_LAT, "o", ms=14, mfc="none", mec="white",
                mew=0.8, alpha=0.65)
    ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3])
    ax.axis("off")
    fig.subplots_adjust(0, 0, 1, 1)
    fig.savefig(path, dpi=dpi, facecolor=BG)
    plt.close(fig)
    print("wrote", path)

out = pathlib.Path("site2/assets"); out.mkdir(parents=True, exist_ok=True)
# full basin hero (wide)
render(out / "hero_lake.png", [extent[0], extent[1], extent[2], extent[3]],
       (13.2, 11.0))
# tight locator crop around the buoy
render(out / "locator.png", [-87.85, -87.30, 41.95, 42.33], (8, 5.6))
print("sst range shown:", round(float(vmin), 2), "to", round(float(vmax), 2), "C")
