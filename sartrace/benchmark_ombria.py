"""Leakage-aware OMBRIA Sentinel-1 flood benchmark.

The public OMBRIA release stores Sentinel-1 VV samples as single-band 8-bit
PNG intensity images. These values are stored digital numbers (DN), not
calibrated sigma0 dB. The benchmark keeps that data contract explicit.

Two evaluation protocols are supported:
1. Official train -> official held-out test and documented 2021 event folders.
2. Leave-one-event-out (LOEO) cross-validation across the four 2021 event
   groups. The held-out event never contributes labels to its fold's threshold
   calibration.

The model-free threshold primitive and signed-change mask are shared with
SARtrace's calibrated GeoTIFF core through sartrace.thresholds.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image

from sartrace.thresholds import median_mad_threshold, signed_change_mask

DATASET_ID = "OMBRIA"
DATASET_VERSION = "Zenodo record 6777870 / GitHub geodrak/OMBRIA"
PAPER_DOI = "10.1109/JSTARS.2022.3155559"
ZENODO_URL = "https://zenodo.org/records/6777870"
GITHUB_URL = "https://github.com/geodrak/OMBRIA"

# These four event directories are documented in the OMBRIA paper's
# out-of-event experiment. EMS 492 (France) is treated separately because the
# paper notes that its regions include geography mapped during EMS 416 in 2019.
EXPECTED_OFFICIAL_SPLIT_COUNTS = {"train": 624, "test": 70}
EXPECTED_EVENT_COUNTS = {"ALBANIA": 22, "TIMOR": 10, "GUYANA": 30, "FRANCE": 88}

EVENTS: dict[str, dict[str, Any]] = {
    "ALBANIA": {
        "ems_event_id": 501,
        "independent_new_event": True,
        "role": "new_event_generalisation",
    },
    "TIMOR": {
        "ems_event_id": 507,
        "independent_new_event": True,
        "role": "new_event_generalisation",
    },
    "GUYANA": {
        "ems_event_id": 514,
        "independent_new_event": True,
        "role": "new_event_generalisation",
    },
    "FRANCE": {
        "ems_event_id": 492,
        "independent_new_event": False,
        "role": "geographic_recurrence_stress",
    },
}


@dataclass(frozen=True)
class OmbriaChip:
    chip_id: str
    before: np.ndarray
    after: np.ndarray
    flood_mask: np.ndarray
    before_path: str
    after_path: str
    mask_path: str
    split: str = "unknown"
    event_country: str | None = None
    ems_event_id: int | None = None
    event_role: str | None = None


@dataclass(frozen=True)
class Calibration:
    after_threshold_dn: int
    after_direction: str
    delta_threshold_dn: int
    delta_direction: str
    train_after_f1: float
    train_delta_f1: float
    otsu_direction: str = "high"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_gray(path: Path) -> np.ndarray:
    """Read one 8-bit grayscale PNG without silently collapsing RGB channels."""
    try:
        with Image.open(path) as image:
            array = np.asarray(image)
    except Exception as exc:  # pragma: no cover - format-specific exception
        raise ValueError(f"Could not read OMBRIA image {path}: {exc}") from exc
    if array.ndim != 2 or array.size == 0:
        raise ValueError(f"Expected a non-empty single-band PNG, got shape {array.shape}: {path}")
    if array.dtype == np.bool_:
        array = array.astype(np.uint8) * 255
    if array.dtype != np.uint8:
        raise ValueError(f"Expected uint8 OMBRIA intensities, got {array.dtype}: {path}")
    return array


def _index_files(folder: Path, pattern: str) -> dict[str, Path]:
    if not folder.is_dir():
        raise FileNotFoundError(f"Dataset split directory not found: {folder}")
    regex = re.compile(pattern)
    found: dict[str, Path] = {}
    for path in sorted(folder.glob("*.png")):
        match = regex.fullmatch(path.name)
        if not match:
            continue
        chip_id = match.group(1)
        if chip_id in found:
            raise ValueError(f"Duplicate chip ID {chip_id} in {folder}")
        found[chip_id] = path
    return found


def _load_triplets(
    before_dir: Path,
    after_dir: Path,
    mask_dir: Path,
    *,
    split: str,
    before_pattern: str,
    after_pattern: str,
    mask_pattern: str,
    event_country: str | None = None,
    ems_event_id: int | None = None,
    event_role: str | None = None,
) -> list[OmbriaChip]:
    before_files = _index_files(before_dir, before_pattern)
    after_files = _index_files(after_dir, after_pattern)
    mask_files = _index_files(mask_dir, mask_pattern)
    before_ids, after_ids, mask_ids = map(set, (before_files, after_files, mask_files))
    if not (before_ids == after_ids == mask_ids):
        raise ValueError(
            f"Unmatched OMBRIA triplets in {before_dir.parent}: "
            f"before-only={sorted(before_ids - after_ids - mask_ids)[:8]}, "
            f"after-only={sorted(after_ids - before_ids - mask_ids)[:8]}, "
            f"mask-only={sorted(mask_ids - before_ids - after_ids)[:8]}, "
            f"missing-before={sorted((after_ids | mask_ids) - before_ids)[:8]}, "
            f"missing-after={sorted((before_ids | mask_ids) - after_ids)[:8]}, "
            f"missing-mask={sorted((before_ids | after_ids) - mask_ids)[:8]}"
        )

    if not before_ids:
        raise ValueError(f"No matched OMBRIA chips found in {before_dir.parent}")
    chips: list[OmbriaChip] = []
    for chip_id in sorted(before_ids, key=lambda value: (int(value) if value.isdigit() else value)):
        before_path = before_files[chip_id]
        after_path = after_files[chip_id]
        mask_path = mask_files[chip_id]
        before = _read_gray(before_path)
        after = _read_gray(after_path)
        raw_mask = _read_gray(mask_path)
        if before.shape != after.shape or before.shape != raw_mask.shape:
            raise ValueError(
                f"Chip {chip_id} has inconsistent dimensions: before={before.shape}, "
                f"after={after.shape}, mask={raw_mask.shape}"
            )
        mask_values = {int(value) for value in np.unique(raw_mask)}
        if not mask_values.issubset({0, 1, 255}):
            raise ValueError(f"Unexpected mask values for chip {chip_id}: {sorted(mask_values)}")
        chips.append(
            OmbriaChip(
                chip_id=str(chip_id),
                before=before,
                after=after,
                flood_mask=raw_mask > 0,
                before_path=str(before_path),
                after_path=str(after_path),
                mask_path=str(mask_path),
                split=split,
                event_country=event_country,
                ems_event_id=ems_event_id,
                event_role=event_role,
            )
        )
    return chips


def load_split(data_root: str | Path, split: str) -> list[OmbriaChip]:
    """Load matched ``OmbriaS1/{split}`` chips, pairing files by numeric ID."""
    if split not in {"train", "test"}:
        raise ValueError("split must be 'train' or 'test'")
    base = Path(data_root) / "OmbriaS1" / split
    return _load_triplets(
        base / "BEFORE", base / "AFTER", base / "MASK",
        split=split,
        before_pattern=r"S1_before_(\d+)\.png",
        after_pattern=r"S1_after_(\d+)\.png",
        mask_pattern=r"S1_mask_(\d+)\.png",
    )


def load_event_split(data_root: str | Path, country: str) -> list[OmbriaChip]:
    """Load an event-held-out Sentinel-1 group from OMBRIA's 2021 folders."""
    key = country.upper()
    if key not in EVENTS:
        raise ValueError(f"Unknown OMBRIA event {country!r}; expected one of {sorted(EVENTS)}")
    metadata = EVENTS[key]
    base = Path(data_root) / "2021" / key / "Sentinel1"
    return _load_triplets(
        base / "BEFORE", base / "AFTER", base / "MASK",
        split="event",
        before_pattern=r"imbefore_(\d+)\.png",
        after_pattern=r"imafter_(\d+)\.png",
        mask_pattern=r"gt_(\d+)\.png",
        event_country=key,
        ems_event_id=int(metadata["ems_event_id"]),
        event_role=str(metadata["role"]),
    )


def load_available_events(data_root: str | Path) -> dict[str, list[OmbriaChip]]:
    """Load all documented 2021 event groups that are present in the archive."""
    root = Path(data_root)
    available: dict[str, list[OmbriaChip]] = {}
    for country in EVENTS:
        base = root / "2021" / country / "Sentinel1"
        if base.exists():
            available[country] = load_event_split(root, country)
    return available


def _counts(pred: np.ndarray, truth: np.ndarray) -> dict[str, int]:
    prediction = np.asarray(pred, dtype=bool)
    reference = np.asarray(truth, dtype=bool)
    if prediction.shape != reference.shape:
        raise ValueError("Prediction and reference mask dimensions differ")
    return {
        "tp": int(np.count_nonzero(prediction & reference)),
        "fp": int(np.count_nonzero(prediction & ~reference)),
        "tn": int(np.count_nonzero(~prediction & ~reference)),
        "fn": int(np.count_nonzero(~prediction & reference)),
    }


def metrics_from_counts(counts: dict[str, int]) -> dict[str, float | int | bool | None]:
    """Compute binary metrics and mark undefined class metrics as ``None``.

    In particular, F1/IoU are undefined (not zero) when both the reference and
    prediction contain no positive pixels. This prevents empty chips from
    silently depressing macro means.
    """
    tp, fp, tn, fn = (int(counts[key]) for key in ("tp", "fp", "tn", "fn"))
    total = tp + fp + tn + fn
    precision_defined = (tp + fp) > 0
    recall_defined = (tp + fn) > 0
    specificity_defined = (tn + fp) > 0
    f1_defined = (2 * tp + fp + fn) > 0
    iou_defined = (tp + fp + fn) > 0
    accuracy_defined = total > 0
    precision = tp / (tp + fp) if precision_defined else None
    recall = tp / (tp + fn) if recall_defined else None
    specificity = tn / (tn + fp) if specificity_defined else None
    f1 = (2 * tp) / (2 * tp + fp + fn) if f1_defined else None
    iou = tp / (tp + fp + fn) if iou_defined else None
    accuracy = (tp + tn) / total if accuracy_defined else None
    balanced_accuracy = (
        (recall + specificity) / 2.0
        if recall is not None and specificity is not None
        else None
    )
    denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = ((tp * tn - fp * fn) / denominator) if denominator else None
    return {
        **counts,
        "pixels": total,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "f1": f1,
        "iou": iou,
        "accuracy": accuracy,
        "balanced_accuracy": balanced_accuracy,
        "mcc": mcc,
        "precision_defined": precision_defined,
        "recall_defined": recall_defined,
        "specificity_defined": specificity_defined,
        "f1_defined": f1_defined,
        "iou_defined": iou_defined,
        "accuracy_defined": accuracy_defined,
        "mcc_defined": denominator > 0,
        "predicted_flood_fraction": (tp + fp) / total if total else None,
        "reference_flood_fraction": (tp + fn) / total if total else None,
    }


def _f1_from_histogram(tp: int, fp: int, fn: int) -> float:
    denominator = 2 * tp + fp + fn
    return (2 * tp / denominator) if denominator else 0.0


def _select_candidate(candidates: list[tuple[float, int, int, str]]) -> tuple[float, int, int, str]:
    if not candidates:
        raise ValueError("No threshold candidates were generated from the training split.")
    # Maximise train F1; on ties choose fewer predicted flood pixels, then a
    # larger threshold magnitude, then a deterministic polarity preference.
    return max(candidates, key=lambda row: (row[0], row[2], row[1], row[3] == "decrease"))


def calibrate_thresholds(train_chips: Iterable[OmbriaChip]) -> Calibration:
    """Select global thresholds using only the supplied training chips' labels."""
    chips = list(train_chips)
    if not chips:
        raise ValueError("At least one training chip is required for threshold calibration.")
    after_flood = np.zeros(256, dtype=np.int64)
    after_nonflood = np.zeros(256, dtype=np.int64)
    delta_flood = np.zeros(511, dtype=np.int64)
    delta_nonflood = np.zeros(511, dtype=np.int64)
    for chip in chips:
        after = chip.after.astype(np.int16)
        before = chip.before.astype(np.int16)
        labels = chip.flood_mask
        np.add.at(after_flood, after[labels], 1)
        np.add.at(after_nonflood, after[~labels], 1)
        bins = (after - before) + 255
        np.add.at(delta_flood, bins[labels], 1)
        np.add.at(delta_nonflood, bins[~labels], 1)
    if int(after_flood.sum()) == 0:
        raise ValueError(
            "Training masks contain no positive flood pixels; thresholds cannot be calibrated."
        )

    after_candidates: list[tuple[float, int, int, str]] = []
    for direction in ("low", "high"):
        if direction == "high":
            true_cumulative = np.cumsum(after_flood[::-1])[::-1]
            false_cumulative = np.cumsum(after_nonflood[::-1])[::-1]
            thresholds = range(0, 256)
        else:
            true_cumulative = np.cumsum(after_flood)
            false_cumulative = np.cumsum(after_nonflood)
            thresholds = range(0, 256)
        for threshold in thresholds:
            tp = int(true_cumulative[threshold])
            fp = int(false_cumulative[threshold])
            fn = int(after_flood.sum()) - tp
            score = _f1_from_histogram(tp, fp, fn)
            after_candidates.append((score, threshold, -(tp + fp), direction))
    best_after = _select_candidate(after_candidates)
    after_f1, after_threshold, _, after_direction = best_after

    delta_candidates: list[tuple[float, int, int, str]] = []
    for direction in ("decrease", "increase"):
        for threshold in range(1, 256):
            if direction == "decrease":
                included = slice(0, 256 - threshold)
            else:
                included = slice(256 + threshold, None)
            tp = int(delta_flood[included].sum())
            fp = int(delta_nonflood[included].sum())
            fn = int(delta_flood.sum()) - tp
            score = _f1_from_histogram(tp, fp, fn)
            delta_candidates.append((score, threshold, -(tp + fp), direction))
    best_delta = _select_candidate(delta_candidates)
    delta_f1, delta_threshold, _, delta_direction = best_delta

    return Calibration(
        after_threshold_dn=int(after_threshold),
        after_direction=str(after_direction),
        delta_threshold_dn=int(delta_threshold),
        delta_direction=str(delta_direction),
        train_after_f1=float(after_f1),
        train_delta_f1=float(delta_f1),
    )


def otsu_threshold_float(values: np.ndarray) -> float:
    """Otsu threshold for a float image on [0, 1], using 256 histogram bins."""
    image = np.asarray(values, dtype=np.float64)
    finite = image[np.isfinite(image)]
    if finite.size == 0:
        return 0.0
    hist, edges = np.histogram(finite, bins=256, range=(0.0, 1.0))
    total = float(hist.sum())
    if total == 0:
        return 0.0
    probability = hist.astype(np.float64) / total
    centers = (edges[:-1] + edges[1:]) / 2.0
    omega = np.cumsum(probability)
    mu = np.cumsum(probability * centers)
    denominator = omega * (1.0 - omega)
    between = np.zeros_like(denominator)
    valid = denominator > 0
    between[valid] = (mu[-1] * omega[valid] - mu[valid]) ** 2 / denominator[valid]
    return float(centers[int(np.argmax(between))])


def _robust_delta_threshold(
    delta: np.ndarray,
    direction: str,
    floor_dn: int,
    mad_multiplier: float,
) -> int:
    signed = np.asarray(delta, dtype=np.float32)
    if direction == "decrease":
        signed = -signed
    elif direction != "increase":
        raise ValueError("direction must be 'decrease' or 'increase'")
    robust = median_mad_threshold(signed, floor=float(floor_dn), multiplier=mad_multiplier)
    return int(min(255, max(floor_dn, math.ceil(robust.threshold))))


METHODS = (
    "otsu_after_original",
    "fixed_after_global",
    "fixed_temporal_delta",
    "robust_temporal_delta",
)


def predict(
    chip: OmbriaChip,
    method: str,
    calibration: Calibration,
    mad_multiplier: float = 3.0,
) -> tuple[np.ndarray, int | None]:
    before = chip.before.astype(np.int16)
    after = chip.after.astype(np.int16)
    delta = after - before
    if method == "otsu_after_original":
        # Reproduces the public OMBRIA notebook's high-side AFTER-image baseline:
        # estimate Otsu on a per-chip min-max copy, apply threshold to AFTER/255.
        after_scaled = chip.after.astype(np.float32) / 255.0
        low, high = float(after_scaled.min()), float(after_scaled.max())
        normalised = (
            (after_scaled - low) / (high - low)
            if high > low
            else np.zeros_like(after_scaled)
        )
        threshold_float = otsu_threshold_float(normalised)
        threshold_dn = int(round(threshold_float * 255.0))
        return after_scaled > threshold_float, threshold_dn
    if method == "fixed_after_global":
        if calibration.after_direction == "high":
            return after >= calibration.after_threshold_dn, calibration.after_threshold_dn
        return after <= calibration.after_threshold_dn, calibration.after_threshold_dn
    if method == "fixed_temporal_delta":
        prediction = signed_change_mask(
            delta,
            threshold=calibration.delta_threshold_dn,
            direction=calibration.delta_direction,  # shared signed-change core primitive
        )
        return prediction, calibration.delta_threshold_dn
    if method == "robust_temporal_delta":
        threshold = _robust_delta_threshold(
            delta, calibration.delta_direction, calibration.delta_threshold_dn, mad_multiplier
        )
        prediction = signed_change_mask(
            delta, threshold=threshold, direction=calibration.delta_direction
        )
        return prediction, threshold
    raise ValueError(f"Unknown method: {method}")


def _aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        empty_counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
        return {
            "n_chips": 0,
            "micro": metrics_from_counts(empty_counts),
            "macro_chip_mean": {},
            "macro_defined_counts": {},
        }
    sums = {key: sum(int(row[key]) for row in rows) for key in ("tp", "fp", "tn", "fn")}
    micro = metrics_from_counts(sums)
    metric_names = (
        "precision", "recall", "specificity", "f1", "iou",
        "accuracy", "balanced_accuracy", "mcc",
    )
    macro: dict[str, float | None] = {}
    defined_counts: dict[str, int] = {}
    for name in metric_names:
        defined = [float(row[name]) for row in rows if row.get(name) is not None]
        macro[name] = float(np.mean(defined)) if defined else None
        defined_counts[name] = len(defined)
    return {
        "n_chips": len(rows),
        "micro": micro,
        "macro_chip_mean": macro,
        "macro_defined_counts": defined_counts,
    }


def _evaluate_chips(
    chips: list[OmbriaChip],
    calibration: Calibration,
    *,
    mad_multiplier: float,
    protocol: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    method_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chip in chips:
        for method in METHODS:
            prediction, threshold = predict(chip, method, calibration, mad_multiplier)
            metrics = metrics_from_counts(_counts(prediction, chip.flood_mask))
            row = {
                "protocol": protocol,
                "split": chip.split,
                "event_country": chip.event_country,
                "ems_event_id": chip.ems_event_id,
                "event_role": chip.event_role,
                "chip_id": chip.chip_id,
                "method": method,
                "threshold_dn": threshold,
                **metrics,
            }
            rows.append(row)
            method_rows[method].append(row)
    aggregate = {method: _aggregate_rows(method_rows[method]) for method in METHODS}
    return rows, aggregate


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _chip_manifest(chip: OmbriaChip) -> dict[str, Any]:
    return {
        "split": chip.split,
        "event_country": chip.event_country,
        "ems_event_id": chip.ems_event_id,
        "chip_id": chip.chip_id,
        "before_file": Path(chip.before_path).name,
        "after_file": Path(chip.after_path).name,
        "mask_file": Path(chip.mask_path).name,
        "before_sha256": _sha256(Path(chip.before_path)),
        "after_sha256": _sha256(Path(chip.after_path)),
        "mask_sha256": _sha256(Path(chip.mask_path)),
    }


def run_benchmark(
    data_root: str | Path,
    output_dir: str | Path,
    *,
    mad_multiplier: float = 3.0,
    include_events: bool = True,
    require_all_events: bool = False,
) -> dict[str, Any]:
    """Calibrate on official train data, then evaluate test and external events.

    Event-held-out scores use the official training split for calibration and
    never use event labels to tune thresholds. LOEO scores are separately
    reported as cross-validation experiments among the four event groups.
    """
    if mad_multiplier < 0:
        raise ValueError("mad_multiplier must be non-negative")
    root = Path(data_root)
    train_chips = load_split(root, "train")
    test_chips = load_split(root, "test")
    train_ids = {chip.chip_id for chip in train_chips}
    test_ids = {chip.chip_id for chip in test_chips}
    overlap = train_ids & test_ids
    if overlap:
        raise ValueError(f"Train/test chip-ID leakage detected: {sorted(overlap)[:10]}")
    calibration = calibrate_thresholds(train_chips)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    test_rows, test_aggregate = _evaluate_chips(
        test_chips, calibration, mad_multiplier=mad_multiplier, protocol="official_train_to_test"
    )
    (out / "calibration.json").write_text(
        json.dumps({
            **asdict(calibration),
            "training_chip_count": len(train_chips),
            "calibration_policy": (
                "Global thresholds selected by pooled training-pixel F1; "
                "test/event masks not used."
            ),
            "tie_break_policy": (
                "Maximum training F1; then fewer predicted-positive pixels; "
                "then larger threshold magnitude."
            ),
            "adaptive_policy": (
                f"Signed-delta median + {mad_multiplier} * 1.4826*MAD, "
                "floored by the train-calibrated delta threshold."
            ),
            "otsu_policy": (
                "Per-chip AFTER-only Otsu high-side threshold following "
                "the public OMBRIA notebook."
            ),
        }, indent=2), encoding="utf-8"
    )

    _write_csv(out / "per_chip_metrics.csv", test_rows)
    method_summary: list[dict[str, Any]] = []
    for method, values in test_aggregate.items():
        row: dict[str, Any] = {"method": method, "test_chips": values["n_chips"]}
        row.update({key: values["micro"].get(key) for key in (
            "precision", "recall", "f1", "iou", "specificity", "mcc",
            "predicted_flood_fraction", "reference_flood_fraction",
        )})
        row.update({
            f"macro_{key}": values["macro_chip_mean"].get(key)
            for key in ("f1", "iou", "precision", "recall")
        })
        method_summary.append(row)
    _write_csv(out / "method_summary.csv", method_summary)

    event_chips_by_country = load_available_events(root) if include_events else {}
    missing_events = [country for country in EVENTS if country not in event_chips_by_country]
    actual_event_counts = {
        country: len(chips) for country, chips in event_chips_by_country.items()
    }
    release_count_check = {
        "expected_official_split_counts": EXPECTED_OFFICIAL_SPLIT_COUNTS,
        "actual_official_split_counts": {"train": len(train_chips), "test": len(test_chips)},
        "expected_event_counts": EXPECTED_EVENT_COUNTS,
        "actual_event_counts": actual_event_counts,
        "official_split_counts_match": {
            split: len(chips) == EXPECTED_OFFICIAL_SPLIT_COUNTS[split]
            for split, chips in (("train", train_chips), ("test", test_chips))
        },
        "event_counts_match": {
            country: actual_event_counts.get(country) == EXPECTED_EVENT_COUNTS[country]
            for country in EVENTS
        },
    }
    release_count_check["full_release_counts_match"] = (
        all(release_count_check["official_split_counts_match"].values())
        and all(release_count_check["event_counts_match"].values())
    )
    if require_all_events and missing_events:
        raise FileNotFoundError(f"Missing documented OMBRIA event groups: {missing_events}")
    if require_all_events and not release_count_check["full_release_counts_match"]:
        raise ValueError(
            "OMBRIA input does not match the published full-release chip counts. "
            "Check for an incomplete download or missing files. Counts: "
            f"{json.dumps(release_count_check, sort_keys=True)}"
        )

    event_rows: list[dict[str, Any]] = []
    event_evaluation: dict[str, Any] = {}
    if event_chips_by_country:
        for country, chips in event_chips_by_country.items():
            rows, aggregate = _evaluate_chips(
                chips, calibration, mad_multiplier=mad_multiplier,
                protocol="official_train_to_event_holdout",
            )
            event_rows.extend(rows)
            meta = EVENTS[country]
            event_evaluation[country] = {
                "ems_event_id": meta["ems_event_id"],
                "event_role": meta["role"],
                "independent_new_event": meta["independent_new_event"],
                "n_chips": len(chips),
                "evaluation": aggregate,
            }
        _write_csv(out / "event_per_chip_metrics.csv", event_rows)

        all_event_rows = event_rows
        new_event_rows = [
            row for row in event_rows
            if row["event_country"] in {"ALBANIA", "TIMOR", "GUYANA"}
        ]
        france_rows = [row for row in event_rows if row["event_country"] == "FRANCE"]
        event_method_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        new_method_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        france_method_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in all_event_rows:
            event_method_rows[row["method"]].append(row)
        for row in new_event_rows:
            new_method_rows[row["method"]].append(row)
        for row in france_rows:
            france_method_rows[row["method"]].append(row)
        event_evaluation["calibration_source"] = {
            "split": "official_train",
            "training_chip_count": len(train_chips),
            "thresholds": asdict(calibration),
            "event_labels_used_for_calibration": False,
        }
        event_evaluation["combined_all_events"] = {
            method: _aggregate_rows(event_method_rows[method]) for method in METHODS
        }
        event_evaluation["combined_new_events_501_507_514"] = {
            method: _aggregate_rows(new_method_rows[method]) for method in METHODS
        }
        event_evaluation["france_492_recurrence_stress"] = (
            {method: _aggregate_rows(france_method_rows[method]) for method in METHODS}
            if france_rows
            else None
        )
        event_summary_rows: list[dict[str, Any]] = []
        for country in event_chips_by_country:
            for method in METHODS:
                values = event_evaluation[country]["evaluation"][method]
                micro = values["micro"]
                macro = values["macro_chip_mean"]
                event_summary_rows.append({
                    "group": country,
                    "ems_event_id": EVENTS[country]["ems_event_id"],
                    "event_role": EVENTS[country]["role"],
                    "method": method,
                    "chips": values["n_chips"],
                    "micro_f1": micro.get("f1"),
                    "micro_iou": micro.get("iou"),
                    "micro_precision": micro.get("precision"),
                    "micro_recall": micro.get("recall"),
                    "macro_chip_f1": macro.get("f1"),
                    "macro_chip_iou": macro.get("iou"),
                })
        combined_groups = (
            ("new_events_501_507_514", event_evaluation["combined_new_events_501_507_514"]),
            ("all_events", event_evaluation["combined_all_events"]),
        )
        if event_evaluation["france_492_recurrence_stress"] is not None:
            combined_groups += ((
                "france_492_recurrence_stress",
                event_evaluation["france_492_recurrence_stress"],
            ),)
        for group_name, group_values in combined_groups:
            for method in METHODS:
                values = group_values[method]
                micro = values["micro"]
                macro = values["macro_chip_mean"]
                event_summary_rows.append({
                    "group": group_name,
                    "ems_event_id": None,
                    "event_role": "combined_group",
                    "method": method,
                    "chips": values["n_chips"],
                    "micro_f1": micro.get("f1"),
                    "micro_iou": micro.get("iou"),
                    "micro_precision": micro.get("precision"),
                    "micro_recall": micro.get("recall"),
                    "macro_chip_f1": macro.get("f1"),
                    "macro_chip_iou": macro.get("iou"),
                })
        _write_csv(out / "event_method_summary.csv", event_summary_rows)

    # Leave-one-event-out CV. This is a separate diagnostic protocol: each
    # fold calibrates on the other available event groups, then evaluates only
    # on the held-out event. It is not mixed with official train -> event scores.
    cv_rows: list[dict[str, Any]] = []
    cv_summary: dict[str, Any] | None = None
    cv_fold_metadata: dict[str, Any] = {}
    if len(event_chips_by_country) >= 2:
        for heldout_country, heldout_chips in event_chips_by_country.items():
            cv_train_chips = [
                chip
                for country, chips in event_chips_by_country.items()
                if country != heldout_country
                for chip in chips
            ]
            fold_calibration = calibrate_thresholds(cv_train_chips)
            cv_fold_metadata[heldout_country] = {
                "heldout_ems_event_id": EVENTS[heldout_country]["ems_event_id"],
                "heldout_chip_count": len(heldout_chips),
                "calibration_event_countries": [
                    country for country in event_chips_by_country
                    if country != heldout_country
                ],
                "calibration_chip_count": len(cv_train_chips),
                "calibration": asdict(fold_calibration),
                "heldout_event_labels_used_for_calibration": False,
            }
            rows, _ = _evaluate_chips(
                heldout_chips, fold_calibration, mad_multiplier=mad_multiplier,
                protocol="leave_one_event_out",
            )
            for row in rows:
                row["heldout_event"] = heldout_country
                row["calibration_events"] = ";".join(
                    country for country in event_chips_by_country if country != heldout_country
                )
            cv_rows.extend(rows)
        _write_csv(out / "event_cross_validation_per_chip.csv", cv_rows)
        cv_by_method: dict[str, Any] = {}
        for method in METHODS:
            method_rows = [row for row in cv_rows if row["method"] == method]
            by_fold = {
                country: _aggregate_rows([
                    row for row in method_rows if row["heldout_event"] == country
                ])
                for country in event_chips_by_country
            }
            cv_by_method[method] = {
                "all_heldout_events": _aggregate_rows(method_rows),
                "per_heldout_event": by_fold,
            }
        cv_summary = {
            "protocol": (
                "Leave-one-event-out cross-validation across available "
                "2021 OMBRIA event groups."
            ),
            "fold_count": len(event_chips_by_country),
            "calibration_policy": (
                "Each fold uses labels from all other event groups; "
                "held-out event labels are used only for scoring."
            ),
            "folds": cv_fold_metadata,
            "evaluation": cv_by_method,
        }
        cv_summary_rows = []
        for method, values in cv_by_method.items():
            micro = values["all_heldout_events"]["micro"]
            macro = values["all_heldout_events"]["macro_chip_mean"]
            cv_summary_rows.append({
                "method": method,
                "folds": len(event_chips_by_country),
                "chips": values["all_heldout_events"]["n_chips"],
                "micro_precision": micro.get("precision"),
                "micro_recall": micro.get("recall"),
                "micro_f1": micro.get("f1"),
                "micro_iou": micro.get("iou"),
                "macro_chip_f1": macro.get("f1"),
                "macro_chip_iou": macro.get("iou"),
            })
        _write_csv(out / "event_cross_validation_summary.csv", cv_summary_rows)

    manifest = {
        "dataset": DATASET_ID,
        "dataset_version": DATASET_VERSION,
        "zenodo_record": ZENODO_URL,
        "zenodo_expected_archive_md5": "3c4cd27b9c869bb32b30c7f10fecced3",
        "note": (
            "SHA-256 is recorded for every input image used in official "
            "calibration, official test and event evaluations."
        ),
        "splits": {
            "train": [_chip_manifest(chip) for chip in train_chips],
            "test": [_chip_manifest(chip) for chip in test_chips],
            "events": {
                country: [_chip_manifest(chip) for chip in chips]
                for country, chips in event_chips_by_country.items()
            },
            "official_train_test_chip_id_overlap_count": len(overlap),
            "train_test_overlap_count": len(overlap),  # compatibility alias for v0.2.0 manifests
            "train_chip_ids": sorted(train_ids),
            "test_chip_ids": sorted(test_ids),
        },
    }
    (out / "input_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    summary = {
        "dataset": DATASET_ID,
        "dataset_version": DATASET_VERSION,
        "paper_doi": PAPER_DOI,
        "source_url": ZENODO_URL,
        "github_url": GITHUB_URL,
        "sensor": "Sentinel-1, single-band VV",
        "image_representation": (
            "8-bit unsigned single-band PNG intensity; native DN, "
            "not calibrated sigma0 dB"
        ),
        "reference_mask": (
            "Binary reference mask derived from Copernicus EMS rapid mapping "
            "products as documented by OMBRIA authors; not exhaustive field-survey truth"
        ),
        "split_counts": {"train": len(train_chips), "test": len(test_chips)},
        "evaluation": test_aggregate,
        "event_counts": actual_event_counts,
        "missing_documented_event_groups": missing_events,
        "release_count_check": release_count_check,
        "event_evaluation_from_official_train_calibration": event_evaluation or None,
        "event_cross_validation": cv_summary,
        "calibration": asdict(calibration),
        "leakage_checks": {
            "official_train_test_chip_id_overlap_count": len(overlap),
            "train_test_overlap_count": len(overlap),  # compatibility alias for v0.2.0 manifests
            "train_chip_ids": sorted(train_ids),
            "test_chip_ids": sorted(test_ids),
            "event_group_ids_are_namespaced_by_country": True,
            "event_heldout_calibration_excludes_heldout_event": True,
        },
        "metric_policy": (
            "Undefined class metrics are null; macro means average only chips "
            "where the metric is defined. Confusion counts and defined-chip counts are retained."
        ),
        "limitations": [
            "OMBRIA PNG values are 8-bit intensity DN, not dB or calibrated physical backscatter.",
            (
                "Copernicus EMS masks are operational reference labels and can contain "
                "timing and boundary uncertainty."
            ),
            (
                "Event 492 France is a recurrence/geographic stress test because the paper "
                "reports overlap with geography mapped during event 416; it is not counted "
                "among the three entirely new events."
            ),
            (
                "The three primary new-event groups are EMS 501 Albania, EMS 507 Timor "
                "and EMS 514 Guyana."
            ),
            "Model-free thresholds are screening baselines, not production flood classifiers.",
            (
                "A result on OMBRIA does not establish generalisation to ICEYE proprietary "
                "SAR imagery or processing chains."
            ),
        ],
    }
    (out / "aggregate_metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
