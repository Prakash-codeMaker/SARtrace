# Architecture and processing contract

## GeoTIFF analysis path

```text
GeoTIFF pair / synthetic test pair
            │
            ▼
     Input adapter (io.py)
            │
            ▼
 Validation and unit conversion (core.py)
   ├─ single-band 2D check
   ├─ shape / CRS / affine-grid check
   ├─ nodata and finite-value mask
   └─ linear power → dB when explicitly selected
            │
            ▼
     Signed difference in dB
       delta = after - before
            │
            ▼
 Shared robust primitive (thresholds.py)
   ├─ median / MAD location-scale estimate
   ├─ floor and multiplier
   └─ one-sided / two-sided signed-change masks
            │
            ▼
  Signed connected components (8-neighbour)
   ├─ decreased backscatter
   └─ increased backscatter
            │
            ▼
   Region ledger + relative evidence index
            │
            ▼
 GeoTIFF / GeoJSON / JSON / ZIP audit bundle
```

## OMBRIA benchmark path (v0.3.0)

```text
OMBRIA official training split (624 chips)
            │
            ▼
 Pair BEFORE / AFTER / MASK by numeric chip ID
            │
            ▼
 Train-only threshold calibration
   ├─ global AFTER threshold + polarity
   └─ global signed temporal-delta threshold + polarity
            │
     ┌──────┴───────────────┐
     ▼                      ▼
Official test (70)   Four documented 2021 event groups (150)
     │                      │
     ▼                      ▼
Train → test metrics  Official train → event holdout metrics
                            │
                            ▼
                   Leave-one-event-out CV
                   (calibrate on other events)
```

- OMBRIA PNG values are 8-bit intensity DN, not dB. The benchmark has a separate data adapter and never routes these values through the calibrated GeoTIFF unit converter.
- Both paths call `sartrace.thresholds.median_mad_threshold` and `signed_change_mask`, with units and calibration policy kept explicit.
- Official train thresholds are not tuned on test/event labels.
- LOEO event folds are separate diagnostic results; each held-out event is excluded from its fold calibration events.
- All used images/masks are SHA-256 hashed into `input_manifest.json`.

## Contracts

- The GeoTIFF app accepts a single raster band per acquisition.
- Both input rasters must have matching dimensions, CRS and affine transform.
- The app does not co-register or silently resample input data.
- Linear input is interpreted as positive **power** backscatter and converted using `10 log10(x)`. Amplitude or DN inputs are not supported.
- Nodata and non-finite cells are excluded from the shared valid mask.
- Positive and negative change candidates are labelled separately to avoid merging adjacent regions of opposite direction.
- The evidence index is relative signal strength, not probability or calibrated confidence.
- GeoJSON geometries are reprojected to WGS84 when a source CRS is available.
- Pixel area is estimated only when the source CRS is projected and has linear units convertible to metres.

## Complexity and current scaling limit

The numerical pipeline is O(N) in pixel count for array operations and connected-component labelling, with memory proportional to raster dimensions. The first prototype loads each full scene into memory. Windowed/chunked raster processing and COG streaming are future extensions; the current app is not an operational large-area processor.
