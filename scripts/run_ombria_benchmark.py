#!/usr/bin/env python3
"""Download OMBRIA (optional) and run leakage-aware S1 benchmarks."""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sartrace.benchmark_ombria import run_benchmark

ZENODO_FILE_URL = "https://zenodo.org/records/6777870/files/OMBRIA-master.zip?download=1"
EXPECTED_MD5 = "3c4cd27b9c869bb32b30c7f10fecced3"


def _md5(path: Path) -> str:
    digest = hashlib.md5()  # nosec: used to verify Zenodo's published archive checksum
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(archive) as zip_file:
        for member in zip_file.infolist():
            candidate = (destination / member.filename).resolve()
            if candidate != destination_resolved and destination_resolved not in candidate.parents:
                raise ValueError(f"Unsafe path in dataset archive: {member.filename}")
        zip_file.extractall(destination)


def ensure_data(data_root: Path, download: bool) -> Path:
    if (data_root / "OmbriaS1" / "train").is_dir():
        return data_root
    nested = data_root / "OMBRIA-master"
    if (nested / "OmbriaS1" / "train").is_dir():
        return nested
    if not download:
        raise FileNotFoundError(
            f"Could not find OmbriaS1/train under {data_root}. "
            "Use --download or extract OMBRIA-master.zip there."
        )

    data_root.mkdir(parents=True, exist_ok=True)
    archive = data_root / "OMBRIA-master.zip"
    print(f"Downloading OMBRIA from {ZENODO_FILE_URL}")
    request = urllib.request.Request(
        ZENODO_FILE_URL,
        headers={"User-Agent": "SARtrace/0.3.0 research benchmark"},
    )
    with urllib.request.urlopen(request, timeout=240) as response, archive.open("wb") as output:
        shutil.copyfileobj(response, output)
    actual_md5 = _md5(archive)
    if actual_md5.lower() != EXPECTED_MD5:
        archive.unlink(missing_ok=True)
        raise ValueError(
            "Downloaded OMBRIA archive failed checksum verification: "
            f"expected MD5 {EXPECTED_MD5}, received {actual_md5}. The partial archive was removed."
        )
    print(f"Downloaded {archive.stat().st_size:,} bytes; MD5 verified. Extracting...")
    _safe_extract(archive, data_root)
    if (data_root / "OmbriaS1" / "train").is_dir():
        return data_root
    if (nested / "OmbriaS1" / "train").is_dir():
        return nested
    raise FileNotFoundError(
        "The Zenodo archive did not contain the expected OmbriaS1/train directory."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root", type=Path, default=Path("data/ombria"),
        help="Directory containing OmbriaS1/train, OmbriaS1/test and optional 2021 event folders",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/ombria-benchmark"))
    parser.add_argument(
        "--download", action="store_true",
        help="Download and checksum-verify OMBRIA from Zenodo",
    )
    parser.add_argument("--mad-multiplier", type=float, default=3.0)
    parser.add_argument(
        "--no-events", action="store_true", help="Skip documented 2021 event folders"
    )
    parser.add_argument(
        "--require-all-events", action="store_true",
        help="Require all documented folders and the published 624/70/150 chip counts",
    )
    args = parser.parse_args()

    root = ensure_data(args.data_root, args.download)
    summary = run_benchmark(
        root,
        args.output_dir,
        mad_multiplier=args.mad_multiplier,
        include_events=not args.no_events,
        require_all_events=args.require_all_events,
    )
    print(
        f"Official split: calibrated on {summary['split_counts']['train']} training chips; "
        f"evaluated on {summary['split_counts']['test']} held-out chips."
    )
    for method, values in summary["evaluation"].items():
        micro = values["micro"]
        f1 = micro["f1"]
        iou = micro["iou"]
        f1_text = f"{f1:.4f}" if f1 is not None else "n/a"
        iou_text = f"{iou:.4f}" if iou is not None else "n/a"
        print(f"{method:24s} F1={f1_text} IoU={iou_text}")

    event_counts = summary.get("event_counts", {})
    if event_counts:
        print(f"Event-held-out chips: {event_counts}")
        print("Event-held-out and LOEO cross-validation reports were written separately.")
    else:
        print("No 2021 event folders were found; event-held-out evaluation was skipped.")
    print(f"Results: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
