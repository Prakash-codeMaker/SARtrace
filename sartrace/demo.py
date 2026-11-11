"""Generate a deterministic synthetic SAR pair for a no-account demo."""
from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter
from rasterio.transform import from_origin
from rasterio.crs import CRS

from .core import RasterScene


def synthetic_pair(size: int = 256, seed: int = 42) -> tuple[RasterScene, RasterScene]:
    if size < 64:
        raise ValueError("Demo size must be at least 64 pixels.")
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size]

    # Broad synthetic scattering zones: open terrain, built-up texture and water.
    background = np.full((size, size), -14.0, dtype=np.float32)
    urban = ((xx - size * 0.70) ** 2 / (size * 0.20) ** 2 + (yy - size * 0.30) ** 2 / (size * 0.17) ** 2) < 1
    water = (yy > size * 0.73) & (xx < size * 0.60)
    background[urban] = -7.5
    background[water] = -21.0

    texture = gaussian_filter(rng.normal(0, 1.0, (size, size)).astype(np.float32), sigma=1.2)
    before = background + texture + rng.normal(0, 0.55, (size, size)).astype(np.float32)
    after = background + texture + rng.normal(0, 0.55, (size, size)).astype(np.float32)

    # Two deliberately synthetic changes: a darkening area and a brightening patch.
    flood_like = ((xx - size * 0.33) ** 2 / (size * 0.12) ** 2 + (yy - size * 0.48) ** 2 / (size * 0.10) ** 2) < 1
    disturbance_like = (xx > size * 0.68) & (xx < size * 0.88) & (yy > size * 0.60) & (yy < size * 0.78)
    after[flood_like] -= 4.2
    after[disturbance_like] += 3.6

    transform = from_origin(400_000, 2_100_000, 10, 10)
    crs = CRS.from_epsg(32643)
    return (
        RasterScene(before, name="SIMULATED_before.tif", units="dB", crs=crs, transform=transform, acquisition_date="2026-10-01 (synthetic)", polarisation="VV"),
        RasterScene(after, name="SIMULATED_after.tif", units="dB", crs=crs, transform=transform, acquisition_date="2026-10-13 (synthetic)", polarisation="VV"),
    )
