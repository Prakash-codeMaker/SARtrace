# Validation plan and limitations

## Automated validation in v0.3.0

The automated suite contains 26 deterministic fixture tests covering:

- positive and negative change detection in the calibrated GeoTIFF core;
- rejection of mismatched shapes, grids and invalid input metadata;
- linear-power to dB conversion and nodata exclusion;
- shared median/MAD threshold and signed-change functions;
- OMBRIA train/test pairing by chip ID;
- OMBRIA event pairing and event metadata;
- rejection of incomplete event triplets and multiband PNGs;
- training-only threshold calibration and rejection of all-negative calibration labels;
- undefined-metric semantics for empty-reference chips;
- official test and leave-one-event-out output generation;
- SHA-256 input manifest generation;
- Zenodo MD5 helper and ZIP path-traversal protection.

These tests establish implementation behavior on deterministic fixtures. They do **not** establish scientific accuracy on real OMBRIA chips or real calibrated Sentinel-1 products.

## Dataset/source cross-check

The Zenodo OMBRIA record lists `OMBRIA-master.zip` as 162.6 MB, MD5 `3c4cd27b9c869bb32b30c7f10fecced3`, and CC BY 4.0. The public repository split has 624 training and 70 test chips. Its 2021 folder structure contains matched BEFORE/AFTER/MASK triplets for Albania (22), Timor (10), Guyana (30) and France (88), totalling 150 event chips. The paper identifies EMS IDs 501, 507, 514 and 492; EMS 501, 507 and 514 are the new-event groups, while France/492 is separated because it includes regions mapped in an earlier French event.

The runtime loader does not trust static counts: it pairs by file ID and validates complete triplets, dimensions, data type and mask values. The downloader checks the Zenodo MD5 before extracting the archive.

## Real-data validation still required

The real OMBRIA archive has not yet been downloaded and processed in this execution environment because the external archive download failed. **No real-data score is available.** On a network-enabled machine, run the command in `docs/OMBRIA_BENCHMARK.md`, then inspect all per-chip and aggregate outputs.

Before making performance claims, review:

1. train-only threshold values and polarity;
2. official test scores with micro and macro metrics;
3. each event score, especially the small Timor sample;
4. combined Albania/Timor/Guyana new-event aggregate;
5. France recurrence/geographic stress-test result separately;
6. LOEO fold calibration metadata and event-specific variance;
7. false positives and false negatives visually, not just scalar metrics;
8. image hashes, archive MD5, dataset citation and CC BY attribution.

Do not report one pooled score without event-separated metrics. Do not describe OMBRIA intensity DN as calibrated dB or masks as field-survey truth.

## Real calibrated Sentinel-1 validation still required

OMBRIA 8-bit PNG benchmark does not replace a real GeoTIFF experiment. A credible real-scene report still needs:

1. source product identifiers, acquisition timestamps and orbit metadata;
2. polarisation and backscatter convention (for example sigma-nought VV dB);
3. preprocessing software and version;
4. calibration, thermal-noise, terrain-correction and co-registration settings;
5. scene alignment and acquisition-geometry QA;
6. manually reviewed ROIs or independent reference annotations;
7. comparison against a fixed-threshold baseline and threshold sensitivity analysis; and
8. reproducible report of parameters, outputs and limitations.

## Interpretation hazards

Backscatter can change due to target change, moisture, vegetation, roughness, incidence geometry, speckle, registration error, seasonal effects or processing differences. A large change region does not establish flood or construction. A darkening candidate is not inherently water; a brightening candidate is not inherently a new building.

## Not yet implemented

- automatic Sentinel-1 catalogue search/download and credential management;
- raw SAFE processing and SNAP/pyroSAR orchestration;
- full orbit/track, incidence-angle and acquisition comparability checks from source metadata;
- automatic co-registration quality measurement;
- multi-temporal baselines and seasonal normalisation;
- windowed/cloud-optimised raster processing;
- learned change models, confidence calibration and multi-polarisation fusion;
- production API, hosted application and QGIS integration.

These limitations should remain visible until the relevant capabilities are implemented and tested.
