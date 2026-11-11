# OMBRIA Sentinel-1 benchmark protocol (SARtrace v0.3.0)

## Research question

How well do simple, transparent, model-free methods identify OMBRIA operational flood reference masks from paired Sentinel-1 VV intensity chips, and how much do results change when a whole flood event is held out?

This benchmark is a **research baseline**, not an operational flood product. It uses released 8-bit PNG intensities. It does not use calibrated sigma-nought dB and does not claim a DN difference is a physical backscatter difference.

## Source dataset and provenance

- Zenodo record: <https://zenodo.org/records/6777870>
- DOI: <https://doi.org/10.5281/zenodo.6777870>
- Dataset/code repository: <https://github.com/geodrak/OMBRIA>
- Paper: Drakonakis et al., *OmbriaNet—Supervised Flood Mapping via Convolutional Neural Networks Using Multitemporal Sentinel-1 and Sentinel-2 Data Fusion*, IEEE JSTARS (2022), DOI <https://doi.org/10.1109/JSTARS.2022.3155559>.
- License shown on Zenodo: CC BY 4.0. Attribute dataset creators and paper when redistributing data or publishing results.
- Zenodo archive: `OMBRIA-master.zip`, 162.6 MB in record file listing, published MD5 `3c4cd27b9c869bb32b30c7f10fecced3`.

The paper reports 844 Sentinel-1 VV tiles across the release: 694 chips in public `OmbriaS1/train` and `OmbriaS1/test`, plus 150 chips in documented 2021 event folders. Each released SAR chip is 256 × 256, single-band VV, 8-bit unsigned intensity. Reference masks derive from Copernicus Emergency Management Service Rapid Mapping products. They are operational reference labels, not exhaustive field-survey truth.

## Dataset layout and documented events

```text
OMBRIA-master/
├── OmbriaS1/
│   ├── train/{BEFORE,AFTER,MASK}/S1_*_NNNN.png
│   └── test/{BEFORE,AFTER,MASK}/S1_*_NNNN.png
└── 2021/
    ├── ALBANIA/Sentinel1/{BEFORE,AFTER,MASK}/...
    ├── FRANCE/Sentinel1/{BEFORE,AFTER,MASK}/...
    ├── GUYANA/Sentinel1/{BEFORE,AFTER,MASK}/...
    └── TIMOR/Sentinel1/{BEFORE,AFTER,MASK}/...
```

Event files use `imbefore_{id}.png`, `imafter_{id}.png`, `gt_{id}.png`. Files are paired by numeric ID, never filesystem order.

| Country | EMS event ID | Chips | Role |
|---|---:|---:|---|
| Albania | 501 | 22 | New-event generalisation |
| Timor | 507 | 10 | New-event generalisation |
| Guyana | 514 | 30 | New-event generalisation |
| France | 492 | 88 | Geographic recurrence stress test |
| **All event folders** | | **150** | |

The paper identifies EMS 501, 507 and 514 as entirely new events. It notes EMS 492 (France) includes regions flooded in 2019 and mapped under EMS event 416. SARtrace reports France separately from the primary three-event new-event aggregate.

The public source repository structure was cross-checked for matching BEFORE/AFTER/MASK counts. Runtime loading validates exact chip IDs, shapes and mask values; static counts do not replace runtime checks.

## Data contract

- `BEFORE`, `AFTER`: single-band 8-bit unsigned image arrays.
- `MASK`: values 0 (non-flood) and positive (flood); loader accepts 1 or 255 as positive encodings and rejects other values.
- Metrics are calculated over pixels in each chip.
- Images are stored intensity DN, not dB, sigma0, gamma0, calibrated power or probability.

SARtrace refuses RGB or multiband PNG inputs rather than silently converting to grayscale. It rejects unmatched IDs, inconsistent shapes, unsupported mask values and empty splits.

## Four model-free methods

1. **`otsu_after_original`** — OMBRIA repository-derived baseline: scale AFTER by 1/255, min-max normalise a copy to estimate an Otsu threshold, then apply that threshold to the original scaled AFTER image. High side is positive, following the public OMBRIA notebook code path.
2. **`fixed_after_global`** — one global threshold on AFTER DN, with high/low polarity chosen using official training labels only.
3. **`fixed_temporal_delta`** — one global threshold on `AFTER - BEFORE` DN, including sign/direction selected using official training labels only.
4. **`robust_temporal_delta`** — one-sided per-chip median/MAD threshold in the training-selected direction, floored by the globally calibrated temporal threshold.

Threshold estimation and signed-change classification are shared primitives with the calibrated GeoTIFF core (`sartrace.thresholds`). Units/calibration policies differ: GeoTIFF uses calibrated dB or linear power; this dataset path uses stored DN.

## Evaluation protocols

### A. Official train → official test
- Calibrate both global thresholds on the public 624-chip training split only.
- Evaluate once on the 70-chip public test split.
- Reject train/test chip-ID overlap.
- Never use test labels to choose thresholds or direction.

### B. Official train → event-held-out evaluation
- Reuse thresholds calibrated on official training data.
- Evaluate each available 2021 event folder separately.
- Report all event folders as a secondary aggregate.
- Report EMS 501, 507 and 514 as the primary new-event aggregate.
- Report France/492 separately as recurrence/geographic stress test.
- Event labels are not used to calibrate this evaluation.

### C. Leave-one-event-out cross-validation (LOEO)
- Treat each country/event folder as one group.
- For each fold, calibrate on all other event groups and score only the held-out group.
- Store held-out EMS ID, training event countries, training chip count and fold thresholds.
- Never use held-out labels to calibrate that fold.

LOEO is a small-sample stability diagnostic, not a substitute for a larger event-disjoint external benchmark. There are only four event groups, and France has a recurrence caveat.

## Shared robust threshold primitive

For finite samples `x`:

```text
center       = median(x)
MAD          = median(abs(x - center))
robust_scale = 1.4826 * MAD
threshold    = max(floor, center + multiplier * robust_scale)
```

- GeoTIFF core: samples are `abs(delta_db)` and classification screens both signs.
- OMBRIA robust baseline: samples are signed DN deltas oriented toward the training-selected direction; classification screens one sign.

Both call `sartrace.thresholds.median_mad_threshold` and `signed_change_mask`.

## Metrics and undefined values

Outputs include TP, FP, TN, FN, precision, recall, specificity, F1, IoU, accuracy, balanced accuracy, MCC and positive-pixel fractions.

- Metrics with zero denominator are `null`, not silently converted to zero.
- Macro chip means average only chips where a metric is defined.
- `macro_defined_counts` records contributing chips per metric.
- Micro metrics aggregate pixel confusion counts over the whole evaluation group.

Do not lead with pixel accuracy alone because flood pixels can be a small fraction of an image.

## Reproducibility and integrity

- Every input image/mask used for train calibration, test scoring and event scoring receives a SHA-256 entry in `input_manifest.json`.
- Downloader checks the Zenodo-published MD5 before extraction.
- ZIP extraction checks member paths to prevent path traversal.
- Calibration parameters and event fold assignments are written to JSON.
- Per-chip results are retained; do not report only one aggregate.

## Run

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
python scripts/run_ombria_benchmark.py --download --require-all-events \\
  --data-root data/ombria --output-dir artifacts/ombria-v0.3
```

For an already extracted archive:

```bash
python scripts/run_ombria_benchmark.py --require-all-events \\
  --data-root path/to/OMBRIA-master --output-dir artifacts/ombria-v0.3
```

To run only the official split, pass `--no-events`.

Outputs: `calibration.json`, `per_chip_metrics.csv`, `method_summary.csv`, `event_per_chip_metrics.csv`, `event_method_summary.csv`, `event_cross_validation_per_chip.csv`, `event_cross_validation_summary.csv`, `aggregate_metrics.json` and `input_manifest.json`.

## Limitations

- OMBRIA PNG values are not calibrated dB; thresholds cannot be transferred directly to ICEYE imagery or SARtrace calibrated GeoTIFF interface.
- Copernicus EMS masks can contain timing, mapping and boundary uncertainty.
- Benchmark covers VV only; it says nothing about VH or dual-polarisation fusion.
- A high score does not prove generalisation to ICEYE sensor, proprietary data, acquisition geometry or processing chain.
- A thresholding baseline is not a flood detector suitable for emergency decisions.
- No real-data score is shipped until the archive is downloaded, checksum verified, benchmark completed and outputs reviewed.

## Citation

Drakonakis et al. (2022), *OmbriaNet—Supervised Flood Mapping via Convolutional Neural Networks Using Multitemporal Sentinel-1 and Sentinel-2 Data Fusion*, IEEE JSTARS. DOI: `10.1109/JSTARS.2022.3155559`.

OMBRIA dataset, Zenodo, DOI: `10.5281/zenodo.6777870`, CC BY 4.0.
