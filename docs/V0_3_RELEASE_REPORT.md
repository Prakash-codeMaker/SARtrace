# SARtrace v0.3.0 — implementation report

**Release date:** 11 November 2026

## Completed in this release

1. **Benchmark/core code reuse.** The GeoTIFF analysis core and OMBRIA benchmark now use the same `median_mad_threshold` and signed-change mask primitives in `sartrace/thresholds.py`. Units remain separate: calibrated dB/linear power for GeoTIFF scenes, stored 8-bit DN for OMBRIA.
2. **Event-held-out evaluation.** Added loaders for Albania/EMS 501 (22 chips), Timor/507 (10), Guyana/514 (30) and France/492 (88). Official train calibration is reused for event scoring without using event labels.
3. **Event cross-validation.** Added leave-one-event-out folds. Each fold stores held-out event, calibration event groups, calibration sample count and threshold parameters.
4. **Event interpretation.** Albania, Timor and Guyana are aggregated as the primary new-event experiment. France is a separate recurrence/geographic stress test because the paper describes overlap with previously mapped French geography.
5. **Metric semantics.** Undefined class metrics are `null`; macro chip means omit undefined values and include contributing chip counts.
6. **Data integrity.** Manifest stores SHA-256 for every training, test and event input. Downloader checks Zenodo MD5 and rejects unsafe archive paths.
7. **Release completeness.** Strict full-release check requires 624 training, 70 test and 150 event chips, split into published event counts.

## Verification performed

- `python -m pytest -q`: **26 passed**.
- `python -m compileall -q sartrace scripts app.py`: passed.
- `python scripts/run_ombria_benchmark.py --help`: passed.
- `pip wheel --no-build-isolation --no-deps`: built `sartrace-0.3.0-py3-none-any.whl`.

## Not completed / claims deliberately withheld

- Zenodo archive download failed in this runtime. No OMBRIA pixels were run through v0.3.0; there are no real-data precision, recall, F1 or IoU values in this release.
- The 26 tests use deterministic fixtures. They validate implementation and leakage-control behavior, not scientific performance.
- Streamlit was unavailable in the build environment, so the interactive app was not launched or browser-tested.
- This release does not download or preprocess raw Sentinel-1 SAFE products, perform co-registration, run SNAP/pyroSAR or process full scenes in raster windows.

## Run the complete benchmark on a network-enabled machine

```bash
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
python scripts/run_ombria_benchmark.py --download --require-all-events \\
  --data-root data/ombria --output-dir artifacts/ombria-v0.3
```

Review `aggregate_metrics.json`, `event_method_summary.csv`, `event_cross_validation_summary.csv`, all per-chip CSVs and `input_manifest.json` before publishing numbers.

## Next engineering priorities

1. Run the OMBRIA full-release benchmark and inspect per-event false positives/false negatives.
2. Obtain two real calibrated/terrain-corrected/co-registered Sentinel-1 GRD scenes and validate the GeoTIFF core against independent reviewed regions.
3. Add acquisition metadata and quality gates (relative orbit, pass direction, incidence-angle range, time gap, preprocessing lineage and registration error).
4. Build windowed/tiled raster IO and preserve pixel-to-map coordinate offsets.
5. Upgrade analyst UI with a map-based before/after swipe, raster toggles and pixel inspector.
6. Add SNAP/pyroSAR orchestration after input contracts and tests are stable.
