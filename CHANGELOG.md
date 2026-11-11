# Changelog

## 0.3.0 — event-held-out validation and shared analysis primitives

- Added a shared median/MAD threshold implementation and signed-change classifier used by both the calibrated GeoTIFF analysis core and OMBRIA benchmark methods.
- Added explicit loaders and manifest metadata for the four documented 2021 OMBRIA Sentinel-1 event groups: EMS 501 Albania, EMS 507 Timor, EMS 514 Guyana and EMS 492 France.
- Added official-training-calibration evaluation on each event group. The three entirely new events are aggregated separately from the France recurrence/geographic stress test.
- Added leave-one-event-out cross-validation across the event groups, with per-fold calibration metadata and held-out label isolation.
- Added explicit undefined-metric handling (`null`) and macro means that exclude undefined per-chip metrics while reporting defined-sample counts.
- Added full SHA-256 manifests for training, test and event images/masks.
- Added training-label validation, stricter single-band uint8 image validation, deterministic threshold tie-breaking and safer archive extraction.
- Added Zenodo MD5 verification using the checksum published on the dataset record.
- Expanded automated coverage from 14 to 26 tests.

No OMBRIA real-data scores are included in this release because the dataset archive could not be downloaded and processed in the build environment. Run the benchmark on a network-enabled machine before citing any performance result.

## 0.2.0 — reproducible OMBRIA benchmark harness

- Added Sentinel-1-only OMBRIA benchmark loader and four model-free baselines.
- Added train-only threshold calibration, official train/test ID-overlap checks, micro/macro metrics and input SHA-256 manifest.
- Documented stored 8-bit DN units and limits of Copernicus EMS reference masks.

## 0.1.0 — initial evidence-first SAR change screening

- Added calibrated single-band GeoTIFF pair validation, dB/linear-power conversion, robust signed-change screening, connected-component filtering and GeoTIFF/GeoJSON/JSON exports.
- Added deterministic synthetic demo, Streamlit interface and core unit tests.
