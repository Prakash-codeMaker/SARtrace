from pathlib import Path

import numpy as np
from PIL import Image

from sartrace.benchmark_ombria import (
    METHODS,
    OmbriaChip,
    _counts,
    calibrate_thresholds,
    load_split,
    metrics_from_counts,
    predict,
)


def _chip(chip_id: str, flooded_level: int = 60) -> OmbriaChip:
    before = np.full((32, 32), 180, dtype=np.uint8)
    after = before.copy()
    mask = np.zeros((32, 32), dtype=bool)
    mask[8:24, 8:24] = True
    after[mask] = flooded_level
    return OmbriaChip(chip_id, before, after, mask, "before.png", "after.png", "mask.png")


def test_metrics_are_correct_for_perfect_prediction():
    truth = np.zeros((4, 4), dtype=bool)
    truth[1:3, 1:3] = True
    result = metrics_from_counts(_counts(truth, truth))
    assert result["f1"] == 1.0
    assert result["iou"] == 1.0
    assert result["mcc"] == 1.0
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0


def test_train_calibration_chooses_decrease_on_training_only():
    train = [_chip("1"), _chip("2")]
    calibration = calibrate_thresholds(train)
    assert calibration.delta_direction == "decrease"
    assert calibration.delta_threshold_dn >= 1
    assert calibration.train_delta_f1 == 1.0


def test_fixed_temporal_delta_predicts_injected_flood_region():
    train = [_chip("1")]
    calibration = calibrate_thresholds(train)
    test = _chip("3")
    pred, threshold = predict(test, "fixed_temporal_delta", calibration)
    assert threshold == calibration.delta_threshold_dn
    assert np.array_equal(pred, test.flood_mask)


def test_adaptive_temporal_method_uses_intensity_units_not_db():
    train = [_chip("1")]
    calibration = calibrate_thresholds(train)
    test = _chip("2")
    pred, threshold = predict(test, "robust_temporal_delta", calibration, mad_multiplier=2.0)
    assert threshold is not None
    assert np.array_equal(pred, test.flood_mask)
    assert len(METHODS) == 4


def test_load_split_pairs_files_by_numeric_id(tmp_path: Path):
    root = tmp_path / "OMBRIA"
    for folder in ("BEFORE", "AFTER", "MASK"):
        (root / "OmbriaS1" / "train" / folder).mkdir(parents=True)
    before = np.full((8, 8), 150, dtype=np.uint8)
    after = before.copy()
    after[2:6, 2:6] = 50
    mask = np.zeros((8, 8), dtype=np.uint8)
    mask[2:6, 2:6] = 255
    Image.fromarray(before).save(root / "OmbriaS1/train/BEFORE/S1_before_0007.png")
    Image.fromarray(after).save(root / "OmbriaS1/train/AFTER/S1_after_0007.png")
    Image.fromarray(mask).save(root / "OmbriaS1/train/MASK/S1_mask_0007.png")
    chips = load_split(root, "train")
    assert len(chips) == 1
    assert chips[0].chip_id == "0007"
    assert chips[0].flood_mask.sum() == 16


def test_run_benchmark_writes_auditable_outputs(tmp_path: Path):
    from sartrace.benchmark_ombria import run_benchmark

    root = tmp_path / "data"
    for split in ("train", "test"):
        for folder in ("BEFORE", "AFTER", "MASK"):
            (root / "OmbriaS1" / split / folder).mkdir(parents=True)
        before = np.full((16, 16), 180, dtype=np.uint8)
        after = before.copy()
        mask = np.zeros((16, 16), dtype=np.uint8)
        after[4:12, 4:12] = 50
        mask[4:12, 4:12] = 255
        idx = "0001" if split == "train" else "0002"
        Image.fromarray(before).save(root / f"OmbriaS1/{split}/BEFORE/S1_before_{idx}.png")
        Image.fromarray(after).save(root / f"OmbriaS1/{split}/AFTER/S1_after_{idx}.png")
        Image.fromarray(mask).save(root / f"OmbriaS1/{split}/MASK/S1_mask_{idx}.png")

    out = tmp_path / "results"
    summary = run_benchmark(root, out)
    assert summary["split_counts"] == {"train": 1, "test": 1}
    assert set(summary["evaluation"]) == set(METHODS)
    assert (out / "calibration.json").is_file()
    assert (out / "per_chip_metrics.csv").is_file()
    assert (out / "method_summary.csv").is_file()
    assert (out / "aggregate_metrics.json").is_file()
    assert (out / "input_manifest.json").is_file()
    manifest = __import__("json").loads((out / "input_manifest.json").read_text())
    assert manifest["splits"]["train_test_overlap_count"] == 0
    assert manifest["splits"]["train_chip_ids"] == ["0001"]


def _write_event(root: Path, country: str, chip_id: str = "0001") -> None:
    base = root / "2021" / country / "Sentinel1"
    for folder in ("BEFORE", "AFTER", "MASK"):
        (base / folder).mkdir(parents=True, exist_ok=True)
    before = np.full((16, 16), 180, dtype=np.uint8)
    after = before.copy()
    mask = np.zeros((16, 16), dtype=np.uint8)
    after[4:12, 4:12] = 50
    mask[4:12, 4:12] = 255
    Image.fromarray(before).save(base / "BEFORE" / f"imbefore_{chip_id}.png")
    Image.fromarray(after).save(base / "AFTER" / f"imafter_{chip_id}.png")
    Image.fromarray(mask).save(base / "MASK" / f"gt_{chip_id}.png")


def test_shared_median_mad_threshold_matches_core_primitive():
    from sartrace.thresholds import median_mad_threshold, signed_change_mask

    values = np.array([0, 0, 0, 0, 10], dtype=np.float32)
    result = median_mad_threshold(values, floor=2.0, multiplier=3.0)
    assert result.center == 0.0
    assert result.robust_scale == 0.0
    assert result.threshold == 2.0
    delta = np.array([[0, -3, 4]], dtype=np.float32)
    decrease = signed_change_mask(delta, threshold=2, direction="decrease")
    increase = signed_change_mask(delta, threshold=2, direction="increase")
    assert decrease.tolist() == [[False, True, False]]
    assert increase.tolist() == [[False, False, True]]


def test_metrics_mark_empty_reference_and_prediction_as_undefined():
    metrics = metrics_from_counts({"tp": 0, "fp": 0, "tn": 16, "fn": 0})
    assert metrics["precision"] is None
    assert metrics["recall"] is None
    assert metrics["f1"] is None
    assert metrics["iou"] is None
    assert metrics["specificity"] == 1.0
    assert metrics["accuracy"] == 1.0


def test_load_event_split_pairs_by_id_and_attaches_event_metadata(tmp_path: Path):
    from sartrace.benchmark_ombria import load_event_split

    _write_event(tmp_path, "ALBANIA", "0013")
    chip = load_event_split(tmp_path, "ALBANIA")[0]
    assert chip.chip_id == "0013"
    assert chip.event_country == "ALBANIA"
    assert chip.ems_event_id == 501
    assert chip.event_role == "new_event_generalisation"
    assert chip.flood_mask.sum() == 64


def test_load_event_split_rejects_missing_pair(tmp_path: Path):
    from sartrace.benchmark_ombria import load_event_split

    _write_event(tmp_path, "TIMOR", "0004")
    (tmp_path / "2021/TIMOR/Sentinel1/AFTER/imafter_0004.png").unlink()
    with np.testing.assert_raises_regex(ValueError, "Unmatched OMBRIA triplets"):
        load_event_split(tmp_path, "TIMOR")


def test_event_heldout_and_leave_one_event_out_are_separate(tmp_path: Path):
    from sartrace.benchmark_ombria import run_benchmark

    root = tmp_path / "data"
    for split, chip_id in (("train", "0001"), ("test", "0002")):
        for folder in ("BEFORE", "AFTER", "MASK"):
            (root / "OmbriaS1" / split / folder).mkdir(parents=True)
        before = np.full((16, 16), 180, dtype=np.uint8)
        after = before.copy()
        mask = np.zeros((16, 16), dtype=np.uint8)
        after[4:12, 4:12] = 50
        mask[4:12, 4:12] = 255
        Image.fromarray(before).save(root / f"OmbriaS1/{split}/BEFORE/S1_before_{chip_id}.png")
        Image.fromarray(after).save(root / f"OmbriaS1/{split}/AFTER/S1_after_{chip_id}.png")
        Image.fromarray(mask).save(root / f"OmbriaS1/{split}/MASK/S1_mask_{chip_id}.png")
    _write_event(root, "ALBANIA", "0001")
    _write_event(root, "TIMOR", "0001")
    _write_event(root, "GUYANA", "0001")
    _write_event(root, "FRANCE", "0001")

    out = tmp_path / "results"
    summary = run_benchmark(root, out)
    assert summary["event_counts"] == {
        "ALBANIA": 1, "TIMOR": 1, "GUYANA": 1, "FRANCE": 1
    }
    assert summary["event_evaluation_from_official_train_calibration"] is not None
    assert summary["event_cross_validation"]["fold_count"] == 4
    event_evaluation = summary["event_evaluation_from_official_train_calibration"]
    assert (
        event_evaluation["combined_new_events_501_507_514"]
        ["fixed_temporal_delta"]["n_chips"] == 3
    )
    assert (
        event_evaluation["france_492_recurrence_stress"]
        ["fixed_temporal_delta"]["n_chips"] == 1
    )
    assert summary["release_count_check"]["full_release_counts_match"] is False
    with np.testing.assert_raises_regex(
        ValueError, "does not match the published full-release chip counts"
    ):
        run_benchmark(root, tmp_path / "strict-results", require_all_events=True)
    assert (out / "event_per_chip_metrics.csv").is_file()
    assert (out / "event_method_summary.csv").is_file()
    assert (out / "event_cross_validation_per_chip.csv").is_file()
    assert (out / "event_cross_validation_summary.csv").is_file()
    manifest = __import__("json").loads((out / "input_manifest.json").read_text())
    assert len(manifest["splits"]["train"]) == 1
    assert len(manifest["splits"]["events"]["ALBANIA"]) == 1
    assert len(manifest["splits"]["train"][0]["before_sha256"]) == 64
    assert len(manifest["splits"]["events"]["FRANCE"][0]["mask_sha256"]) == 64


def test_calibration_rejects_training_with_no_flood_pixels():
    chip = _chip("empty")
    chip = OmbriaChip(
        chip.chip_id, chip.before, chip.after, np.zeros_like(chip.flood_mask),
        chip.before_path, chip.after_path, chip.mask_path,
    )
    with np.testing.assert_raises_regex(ValueError, "no positive flood pixels"):
        calibrate_thresholds([chip])


def test_macro_chip_metrics_exclude_undefined_empty_chip_metrics():
    from sartrace.benchmark_ombria import _aggregate_rows

    empty = metrics_from_counts({"tp": 0, "fp": 0, "tn": 16, "fn": 0})
    perfect = metrics_from_counts({"tp": 16, "fp": 0, "tn": 48, "fn": 0})
    rows = [{**empty}, {**perfect}]
    aggregated = _aggregate_rows(rows)
    assert aggregated["macro_chip_mean"]["f1"] == 1.0
    assert aggregated["macro_defined_counts"]["f1"] == 1


def test_official_train_test_id_overlap_is_rejected(tmp_path: Path):
    from sartrace.benchmark_ombria import run_benchmark

    root = tmp_path / "data"
    for split in ("train", "test"):
        for folder in ("BEFORE", "AFTER", "MASK"):
            (root / "OmbriaS1" / split / folder).mkdir(parents=True)
        before = np.full((8, 8), 180, dtype=np.uint8)
        after = before.copy()
        mask = np.zeros((8, 8), dtype=np.uint8)
        after[2:6, 2:6] = 50
        mask[2:6, 2:6] = 255
        Image.fromarray(before).save(root / f"OmbriaS1/{split}/BEFORE/S1_before_0001.png")
        Image.fromarray(after).save(root / f"OmbriaS1/{split}/AFTER/S1_after_0001.png")
        Image.fromarray(mask).save(root / f"OmbriaS1/{split}/MASK/S1_mask_0001.png")
    with np.testing.assert_raises_regex(ValueError, "Train/test chip-ID leakage"):
        run_benchmark(root, tmp_path / "out")


def test_require_all_events_fails_when_an_event_group_is_missing(tmp_path: Path):
    from sartrace.benchmark_ombria import run_benchmark

    root = tmp_path / "data"
    for split, chip_id in (("train", "0001"), ("test", "0002")):
        for folder in ("BEFORE", "AFTER", "MASK"):
            (root / "OmbriaS1" / split / folder).mkdir(parents=True)
        before = np.full((8, 8), 180, dtype=np.uint8)
        after = before.copy()
        mask = np.zeros((8, 8), dtype=np.uint8)
        after[2:6, 2:6] = 50
        mask[2:6, 2:6] = 255
        Image.fromarray(before).save(root / f"OmbriaS1/{split}/BEFORE/S1_before_{chip_id}.png")
        Image.fromarray(after).save(root / f"OmbriaS1/{split}/AFTER/S1_after_{chip_id}.png")
        Image.fromarray(mask).save(root / f"OmbriaS1/{split}/MASK/S1_mask_{chip_id}.png")
    with np.testing.assert_raises_regex(
        FileNotFoundError, "Missing documented OMBRIA event groups"
    ):
        run_benchmark(root, tmp_path / "out", require_all_events=True)


def test_png_loader_rejects_multiband_images(tmp_path: Path):
    from sartrace.benchmark_ombria import _read_gray

    path = tmp_path / "rgb.png"
    Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8)).save(path)
    with np.testing.assert_raises_regex(ValueError, "single-band PNG"):
        _read_gray(path)


def test_zenodo_archive_extractor_rejects_path_traversal(tmp_path: Path):
    import zipfile

    from scripts.run_ombria_benchmark import _safe_extract

    archive = tmp_path / "unsafe.zip"
    destination = tmp_path / "extract"
    destination.mkdir()
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("../outside.txt", "not allowed")
    with np.testing.assert_raises_regex(ValueError, "Unsafe path"):
        _safe_extract(archive, destination)
    assert not (tmp_path / "outside.txt").exists()


def test_zenodo_archive_md5_helper_matches_known_value(tmp_path: Path):
    from scripts.run_ombria_benchmark import _md5

    path = tmp_path / "small.txt"
    path.write_text("SARtrace", encoding="utf-8")
    assert _md5(path) == "377c6a5d7e4a0d6f8e92d01865921e14"
