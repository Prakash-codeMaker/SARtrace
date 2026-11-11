import numpy as np
import pytest
from rasterio.transform import from_origin
from rasterio.crs import CRS

from sartrace.core import RasterScene, analyse_pair, validate_pair
from sartrace.demo import synthetic_pair


def test_synthetic_demo_detects_both_signed_changes():
    before, after = synthetic_pair(size=192)
    result = analyse_pair(before, after, min_change_db=1.5, sigma_multiplier=2.5, min_region_pixels=8)
    assert result.valid_fraction > 0.99
    assert result.summary["decreased_backscatter_pixels"] > 50
    assert result.summary["increased_backscatter_pixels"] > 50
    assert result.threshold_db >= 1.5
    assert len(result.regions) >= 2
    assert result.summary["pixel_area_m2"] == pytest.approx(100.0)


def test_rejects_shape_mismatch():
    a = RasterScene(np.ones((20, 20)), crs="EPSG:32643", transform=from_origin(1, 1, 1, 1))
    b = RasterScene(np.ones((21, 20)), crs="EPSG:32643", transform=from_origin(1, 1, 1, 1))
    with pytest.raises(ValueError, match="dimensions differ"):
        validate_pair(a, b)


def test_rejects_transform_mismatch_instead_of_silent_resampling():
    a = RasterScene(np.ones((20, 20)), crs=CRS.from_epsg(32643), transform=from_origin(100, 200, 10, 10))
    b = RasterScene(np.ones((20, 20)), crs=CRS.from_epsg(32643), transform=from_origin(110, 200, 10, 10))
    with pytest.raises(ValueError, match="transforms differ"):
        validate_pair(a, b)


def test_linear_power_is_converted_to_db():
    values = np.full((30, 30), 0.1, dtype=np.float32)
    before = RasterScene(values, units="linear", crs=CRS.from_epsg(32643), transform=from_origin(100, 200, 10, 10))
    after = RasterScene(values * 2, units="linear", crs=CRS.from_epsg(32643), transform=from_origin(100, 200, 10, 10))
    result = analyse_pair(before, after, min_change_db=0.5, sigma_multiplier=0, min_region_pixels=1)
    assert np.allclose(result.before_db, -10.0, atol=1e-4)
    assert np.allclose(result.delta_db, 10 * np.log10(2), atol=1e-4)


def test_nodata_is_excluded_from_analysis():
    before_values = np.full((30, 30), -12.0, dtype=np.float32)
    after_values = before_values.copy()
    before_values[0:5, 0:5] = -9999
    after_values[0:5, 0:5] = -9999
    after_values[10:20, 10:20] = -8.0
    transform = from_origin(100, 200, 10, 10)
    crs = CRS.from_epsg(32643)
    before = RasterScene(before_values, nodata=-9999, crs=crs, transform=transform)
    after = RasterScene(after_values, nodata=-9999, crs=crs, transform=transform)
    result = analyse_pair(before, after, min_change_db=1.0, sigma_multiplier=0, min_region_pixels=3)
    assert result.valid_fraction == pytest.approx(875 / 900)
    assert np.all(result.change_mask[0:5, 0:5] == 255)


def test_invalid_parameters_rejected():
    before, after = synthetic_pair(size=64)
    with pytest.raises(ValueError, match="at least 0.1"):
        analyse_pair(before, after, min_change_db=0)


def test_rejects_polarisation_mismatch():
    transform = from_origin(100, 200, 10, 10)
    crs = CRS.from_epsg(32643)
    a = RasterScene(np.full((20, 20), -12.0), crs=crs, transform=transform, polarisation="VV")
    b = RasterScene(np.full((20, 20), -12.0), crs=crs, transform=transform, polarisation="VH")
    with pytest.raises(ValueError, match="Polarisation differs"):
        validate_pair(a, b)


def test_geotiff_round_trip_and_bundle_contents():
    import io
    import json
    import zipfile

    from sartrace.io import build_bundle, geotiff_bytes, read_scene

    before, after = synthetic_pair(size=96)
    before_bytes = geotiff_bytes(before.values, before, dtype="float32", nodata=-9999.0, description="VV dB")
    after_bytes = geotiff_bytes(after.values, after, dtype="float32", nodata=-9999.0, description="VV dB")
    loaded_before = read_scene(before_bytes, name="before.tif", units="dB", polarisation="VV")
    loaded_after = read_scene(after_bytes, name="after.tif", units="dB", polarisation="VV")
    result = analyse_pair(loaded_before, loaded_after)
    bundle = build_bundle(loaded_before, loaded_after, result)
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert set(archive.namelist()) == {
            "delta_backscatter_db.tif",
            "change_candidates.tif",
            "relative_evidence_index.tif",
            "change_regions.geojson",
            "analysis_report.json",
        }
        report = json.loads(archive.read("analysis_report.json"))
        assert report["product"] == "SARtrace"
        assert report["source_data_mode"] == "user_supplied_geotiff"
        assert report["inputs"]["before"]["polarisation"] == "VV"
        geojson = json.loads(archive.read("change_regions.geojson"))
        assert geojson["metadata"]["geometry_crs"] == "EPSG:4326"
