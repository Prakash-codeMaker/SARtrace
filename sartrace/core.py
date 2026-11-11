"""Core, dependency-light SAR change analysis primitives for SARtrace."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from scipy import ndimage

from sartrace.thresholds import median_mad_threshold, two_sided_change_masks


@dataclass(frozen=True)
class RasterScene:
    """A single-band, calibrated SAR backscatter scene.

    ``values`` may be dB or linear power backscatter. Real inputs should be
    calibrated, terrain-corrected and co-registered before they reach SARtrace.
    """

    values: np.ndarray
    name: str = "scene"
    units: str = "dB"
    nodata: Optional[float] = None
    crs: Any = None
    transform: Any = None
    acquisition_date: Optional[str] = None
    sha256: Optional[str] = None
    polarisation: Optional[str] = None


@dataclass
class ChangeRegion:
    region_id: int
    direction: str
    pixels: int
    mean_delta_db: float
    median_delta_db: float
    max_abs_delta_db: float
    bounds_px: tuple[int, int, int, int]
    area_m2: Optional[float] = None


@dataclass
class AnalysisResult:
    before_db: np.ndarray
    after_db: np.ndarray
    delta_db: np.ndarray
    change_mask: np.ndarray
    component_labels: np.ndarray
    evidence_index: np.ndarray
    valid_mask: np.ndarray
    threshold_db: float
    median_abs_delta_db: float
    robust_noise_db: float
    valid_fraction: float
    regions: list[ChangeRegion] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def _to_db(values: np.ndarray, units: str) -> np.ndarray:
    data = np.asarray(values, dtype=np.float32)
    normalized = units.strip().lower()
    if normalized in {"db", "decibel", "decibels"}:
        return data.copy()
    if normalized in {"linear", "power", "sigma0", "gamma0", "linear power"}:
        positive = np.where(data > 0, data, np.nan)
        with np.errstate(divide="ignore", invalid="ignore"):
            return (10.0 * np.log10(positive)).astype(np.float32)
    raise ValueError("Units must be 'dB' or 'linear power'.")


def _grid_signature(transform: Any) -> Optional[np.ndarray]:
    if transform is None:
        return None
    try:
        return np.asarray(tuple(transform)[:6], dtype=np.float64)
    except (TypeError, ValueError):
        return None


def validate_pair(before: RasterScene, after: RasterScene) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Validate shapes/grids and return dB arrays plus a shared valid mask.

    SARtrace deliberately refuses to silently warp or resample an input scene.
    Pixel-level change analysis is only meaningful when both arrays describe
    the same ground grid. Use a SAR preprocessing tool before analysis if not.
    """
    a = np.asarray(before.values)
    b = np.asarray(after.values)
    if a.ndim != 2 or b.ndim != 2:
        raise ValueError("Each input must be a single-band 2D raster. Select one band before upload.")
    if a.shape != b.shape:
        raise ValueError(
            f"Raster dimensions differ: before={a.shape}, after={b.shape}. "
            "Co-register and export both scenes on the same pixel grid first."
        )
    if before.crs is not None and after.crs is not None and str(before.crs) != str(after.crs):
        raise ValueError("Coordinate reference systems differ. Reproject and co-register the scenes first.")
    if (before.crs is None) != (after.crs is None):
        raise ValueError("Only one scene has a CRS. Both scenes must have matching geospatial metadata.")
    if before.polarisation and after.polarisation and before.polarisation != after.polarisation:
        raise ValueError("Polarisation differs between scenes. Compare the same polarisation (for example, VV with VV).")
    if (before.polarisation is None) != (after.polarisation is None):
        raise ValueError("Polarisation is recorded for only one scene. Record the same polarisation for both, or mark both as unknown.")
    ta, tb = _grid_signature(before.transform), _grid_signature(after.transform)
    if ta is not None and tb is not None and not np.allclose(ta, tb, rtol=0, atol=1e-8):
        raise ValueError(
            "Raster transforms differ. SARtrace will not silently resample SAR data; "
            "co-register both scenes to the same grid first."
        )
    if (ta is None) != (tb is None):
        raise ValueError("Only one scene has an affine transform. Both scenes need matching grid metadata.")

    before_db = _to_db(a, before.units)
    after_db = _to_db(b, after.units)
    valid = np.isfinite(before_db) & np.isfinite(after_db)
    if before.nodata is not None:
        valid &= a != before.nodata
    if after.nodata is not None:
        valid &= b != after.nodata
    if int(valid.sum()) < 25:
        raise ValueError("Fewer than 25 shared valid pixels remain; the scenes cannot be analysed reliably.")
    return before_db, after_db, valid


def _pixel_area_m2(scene: RasterScene) -> Optional[float]:
    """Return approximate pixel area for projected metric CRSs only."""
    if scene.transform is None or scene.crs is None:
        return None
    try:
        crs = scene.crs
        if not crs.is_projected:
            return None
        # Rasterio CRS exposes linear_units_factor as (unit_name, metres_per_unit).
        if hasattr(crs, "linear_units_factor"):
            factor = float(crs.linear_units_factor[1])
        else:
            from pyproj import CRS as PyprojCRS
            axes = PyprojCRS.from_user_input(crs).axis_info
            factor = float(axes[0].unit_conversion_factor) if axes else 1.0
        t = scene.transform
        determinant = abs(float(t.a) * float(t.e) - float(t.b) * float(t.d))
        return determinant * factor * factor
    except (AttributeError, TypeError, ValueError, IndexError):
        return None


def analyse_pair(
    before: RasterScene,
    after: RasterScene,
    *,
    min_change_db: float = 1.5,
    sigma_multiplier: float = 3.0,
    min_region_pixels: int = 8,
) -> AnalysisResult:
    """Find signed backscatter-change candidates using a robust global threshold.

    Mask convention: 0 = stable, 1 = decreased backscatter, 2 = increased
    backscatter, 255 = invalid. ``evidence_index`` is a relative signal-strength
    index, not a probability or calibrated confidence score.
    """
    if min_change_db < 0.1:
        raise ValueError("Minimum change threshold must be at least 0.1 dB.")
    if sigma_multiplier < 0:
        raise ValueError("Robust-noise multiplier cannot be negative.")
    if min_region_pixels < 1:
        raise ValueError("Minimum region size must be at least one pixel.")

    before_db, after_db, valid = validate_pair(before, after)
    delta = np.full(before_db.shape, np.nan, dtype=np.float32)
    delta[valid] = after_db[valid] - before_db[valid]
    abs_delta = np.abs(delta[valid]).astype(np.float64)

    robust_threshold = median_mad_threshold(
        abs_delta, floor=min_change_db, multiplier=sigma_multiplier
    )
    median_abs = robust_threshold.center
    robust_noise = robust_threshold.robust_scale
    threshold = robust_threshold.threshold
    raw_decrease, raw_increase = two_sided_change_masks(
        delta, threshold=threshold, valid_mask=valid
    )
    mask = np.zeros(delta.shape, dtype=np.uint8)
    mask[~valid] = 255
    labels = np.zeros(delta.shape, dtype=np.int32)
    regions: list[ChangeRegion] = []
    next_id = 1
    pixel_area = _pixel_area_m2(before)

    # Label the two directions separately so touching positive/negative
    # candidates cannot collapse into one mixed-direction polygon.
    for raw, direction, code in (
        (raw_decrease, "decreased_backscatter", 1),
        (raw_increase, "increased_backscatter", 2),
    ):
        component_map, count = ndimage.label(raw, structure=np.ones((3, 3), dtype=np.uint8))
        if count == 0:
            continue
        sizes = np.bincount(component_map.ravel())
        for local_id in range(1, count + 1):
            pixels = int(sizes[local_id])
            if pixels < min_region_pixels:
                continue
            component = component_map == local_id
            ys, xs = np.where(component)
            values = delta[component]
            labels[component] = next_id
            mask[component] = code
            regions.append(
                ChangeRegion(
                    region_id=next_id,
                    direction=direction,
                    pixels=pixels,
                    mean_delta_db=float(np.mean(values)),
                    median_delta_db=float(np.median(values)),
                    max_abs_delta_db=float(np.max(np.abs(values))),
                    bounds_px=(int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1),
                    area_m2=(float(pixels * pixel_area) if pixel_area is not None else None),
                )
            )
            next_id += 1

    evidence = np.full(delta.shape, np.nan, dtype=np.float32)
    scale = max(robust_noise, 0.25)
    evidence[valid] = (np.abs(delta[valid]) / scale).astype(np.float32)

    decrease_pixels = int(np.count_nonzero(mask == 1))
    increase_pixels = int(np.count_nonzero(mask == 2))
    valid_pixels = int(np.count_nonzero(valid))
    total_pixels = int(valid.size)
    summary: dict[str, Any] = {
        "valid_pixels": valid_pixels,
        "total_pixels": total_pixels,
        "valid_fraction": float(valid_pixels / total_pixels),
        "decreased_backscatter_pixels": decrease_pixels,
        "increased_backscatter_pixels": increase_pixels,
        "candidate_change_pixels": decrease_pixels + increase_pixels,
        "candidate_change_fraction_of_valid": float((decrease_pixels + increase_pixels) / valid_pixels),
        "region_count": len(regions),
        "minimum_change_threshold_db": float(min_change_db),
        "robust_noise_multiplier": float(sigma_multiplier),
        "selected_threshold_db": threshold,
        "median_absolute_delta_db": median_abs,
        "robust_noise_scale_db": robust_noise,
        "minimum_region_pixels": int(min_region_pixels),
        "pixel_area_m2": pixel_area,
    }
    return AnalysisResult(
        before_db=before_db,
        after_db=after_db,
        delta_db=delta,
        change_mask=mask,
        component_labels=labels,
        evidence_index=evidence,
        valid_mask=valid,
        threshold_db=threshold,
        median_abs_delta_db=median_abs,
        robust_noise_db=robust_noise,
        valid_fraction=float(valid_pixels / total_pixels),
        regions=regions,
        summary=summary,
    )
