"""GeoTIFF input/output and portable analysis bundle generation."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any

import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.io import MemoryFile
from rasterio.warp import transform_geom

from .core import AnalysisResult, RasterScene


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_scene(data: bytes, *, name: str, units: str, acquisition_date: str | None = None, polarisation: str | None = None) -> RasterScene:
    """Read the first band of an uploaded GeoTIFF, preserving grid metadata."""
    try:
        with MemoryFile(data) as memfile:
            with memfile.open() as dataset:
                if dataset.count != 1:
                    raise ValueError(f"{name} has {dataset.count} bands. Export the chosen VV or VH band as a single-band GeoTIFF first.")
                if dataset.crs is None or dataset.transform is None:
                    raise ValueError(f"{name} is missing a CRS or affine transform. SARtrace needs georeferenced GeoTIFF input.")
                arr = dataset.read(1).astype(np.float32)
                nodata = dataset.nodata
                return RasterScene(
                    values=arr,
                    name=name,
                    units=units,
                    nodata=nodata,
                    crs=dataset.crs,
                    transform=dataset.transform,
                    acquisition_date=acquisition_date,
                    sha256=sha256_bytes(data),
                    polarisation=polarisation,
                )
    except rasterio.errors.RasterioError as exc:
        raise ValueError(f"Could not read {name} as a GeoTIFF: {exc}") from exc


def geotiff_bytes(
    array: np.ndarray,
    template: RasterScene,
    *,
    dtype: str,
    nodata: int | float,
    description: str,
) -> bytes:
    if template.transform is None or template.crs is None:
        raise ValueError("GeoTIFF export requires an input with CRS and affine transform metadata.")
    data = np.asarray(array, dtype=dtype)
    profile: dict[str, Any] = {
        "driver": "GTiff",
        "height": data.shape[0],
        "width": data.shape[1],
        "count": 1,
        "dtype": dtype,
        "crs": template.crs,
        "transform": template.transform,
        "compress": "deflate",
        "predictor": 3 if dtype.startswith("float") else 2,
        "nodata": nodata,
        "tiled": True,
    }
    with MemoryFile() as memfile:
        with memfile.open(**profile) as dst:
            dst.write(data, 1)
            dst.set_band_description(1, description)
        return memfile.read()


def geojson_dict(result: AnalysisResult, template: RasterScene) -> dict[str, Any]:
    if template.transform is None or template.crs is None:
        raise ValueError("GeoJSON export requires both a CRS and affine transform.")
    features = []
    props_by_id = {r.region_id: r for r in result.regions}
    for geom, value in shapes(
        result.component_labels.astype(np.int32),
        mask=result.component_labels > 0,
        transform=template.transform,
        connectivity=8,
    ):
        region = props_by_id.get(int(value))
        if region is None:
            continue
        props = {
            "region_id": region.region_id,
            "direction": region.direction,
            "pixels": region.pixels,
            "mean_delta_db": round(region.mean_delta_db, 4),
            "median_delta_db": round(region.median_delta_db, 4),
            "max_abs_delta_db": round(region.max_abs_delta_db, 4),
        }
        if region.area_m2 is not None:
            props["area_m2_approx"] = round(region.area_m2, 2)
        if template.crs is not None and str(template.crs) != "EPSG:4326":
            geom = transform_geom(template.crs, "EPSG:4326", geom, precision=6)
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return {
        "type": "FeatureCollection",
        "name": "SARtrace_change_candidates",
        "features": features,
        "metadata": {
            "note": "Candidate backscatter changes; not semantic labels or validated event detections.",
            "source_crs": str(template.crs) if template.crs else None,
            "geometry_crs": "EPSG:4326",
            "synthetic_test_data": bool(template.name.startswith("SIMULATED")),
        },
    }


def geojson_bytes(result: AnalysisResult, template: RasterScene) -> bytes:
    return json.dumps(geojson_dict(result, template), indent=2).encode("utf-8")


def report_dict(before: RasterScene, after: RasterScene, result: AnalysisResult) -> dict[str, Any]:
    return {
        "product": "SARtrace",
        "version": "0.3.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_type": "two-date signed SAR backscatter change screening",
        "source_data_mode": "synthetic_test_data" if before.name.startswith("SIMULATED") else "user_supplied_geotiff",
        "inputs": {
            "before": {
                "name": before.name,
                "acquisition_date": before.acquisition_date,
                "units_as_uploaded": before.units,
                "polarisation": before.polarisation,
                "sha256": before.sha256,
            },
            "after": {
                "name": after.name,
                "acquisition_date": after.acquisition_date,
                "units_as_uploaded": after.units,
                "polarisation": after.polarisation,
                "sha256": after.sha256,
            },
            "crs": str(before.crs) if before.crs else None,
            "shape": list(before.values.shape),
            "grid_policy": "strict: matching dimensions, CRS and affine transform required; no silent resampling",
        },
        "method": {
            "backscatter_comparison": "delta_db = after_db - before_db",
            "threshold_method": "max(minimum_change_db, median(abs(delta_db)) + sigma_multiplier * 1.4826 * MAD(abs(delta_db)))",
            "evidence_index": "abs(delta_db) / max(robust_noise_scale_db, 0.25); relative index, not probability",
            "connected_components": "8-connected; positive and negative changes labelled separately",
            **{k: result.summary[k] for k in [
                "minimum_change_threshold_db", "robust_noise_multiplier", "selected_threshold_db",
                "median_absolute_delta_db", "robust_noise_scale_db", "minimum_region_pixels"
            ]},
        },
        "summary": result.summary,
        "regions": [
            {
                "region_id": r.region_id,
                "direction": r.direction,
                "pixels": r.pixels,
                "mean_delta_db": r.mean_delta_db,
                "median_delta_db": r.median_delta_db,
                "max_abs_delta_db": r.max_abs_delta_db,
                "bounds_px": list(r.bounds_px),
                "area_m2_approx": r.area_m2,
            }
            for r in result.regions
        ],
        "interpretation_guardrails": [
            "A backscatter increase or decrease is a signal change candidate, not a semantic class.",
            "Do not label a candidate as flood, construction, vehicle, damage or another event without independent evidence.",
            "The algorithm does not calibrate, terrain-correct, deburst, remove thermal noise, or co-register raw SAR acquisitions.",
            "Use comparable polarisation, orbit geometry, incidence-angle conditions and preprocessing for meaningful comparisons.",
        ],
    }


def build_bundle(before: RasterScene, after: RasterScene, result: AnalysisResult) -> bytes:
    """Create a portable ZIP containing rasters, polygons and an audit report."""
    if before.crs is None or before.transform is None:
        raise ValueError("Download bundle requires georeferenced GeoTIFF inputs.")
    report = report_dict(before, after, result)
    files = {
        "delta_backscatter_db.tif": geotiff_bytes(
            np.where(result.valid_mask, result.delta_db, -9999.0), before, dtype="float32", nodata=-9999.0,
            description="After minus before backscatter in dB",
        ),
        "change_candidates.tif": geotiff_bytes(
            np.where(result.change_mask == 255, 255, result.change_mask), before,
            dtype="uint8", nodata=255,
            description="0 stable, 1 decreased, 2 increased, 255 invalid",
        ),
        "relative_evidence_index.tif": geotiff_bytes(
            np.where(result.valid_mask, result.evidence_index, -9999.0), before,
            dtype="float32", nodata=-9999.0,
            description="Relative absolute-change index; not probability",
        ),
        "change_regions.geojson": geojson_bytes(result, before),
        "analysis_report.json": json.dumps(report, indent=2).encode("utf-8"),
    }
    buff = io.BytesIO()
    with zipfile.ZipFile(buff, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)
    return buff.getvalue()
