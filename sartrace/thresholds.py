"""Shared robust threshold and signed-change primitives used by SARtrace workflows."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

Direction = Literal["decrease", "increase"]


@dataclass(frozen=True)
class RobustThreshold:
    center: float
    mad: float
    robust_scale: float
    threshold: float
    sample_count: int


def median_mad_threshold(
    values: np.ndarray,
    *,
    floor: float,
    multiplier: float,
) -> RobustThreshold:
    """Return ``max(floor, median + multiplier * 1.4826*MAD)``.

    The caller is responsible for choosing the meaningful input quantity:
    absolute dB change for the calibrated GeoTIFF workflow, or signed DN
    change for the OMBRIA dataset-specific benchmark.
    """
    if floor < 0:
        raise ValueError("Threshold floor must be non-negative.")
    if multiplier < 0:
        raise ValueError("MAD multiplier must be non-negative.")
    samples = np.asarray(values, dtype=np.float64).ravel()
    samples = samples[np.isfinite(samples)]
    if samples.size == 0:
        raise ValueError("Cannot estimate a robust threshold from zero finite samples.")
    center = float(np.median(samples))
    mad = float(np.median(np.abs(samples - center)))
    robust_scale = float(1.4826 * mad)
    threshold = float(max(floor, center + multiplier * robust_scale))
    return RobustThreshold(
        center=center,
        mad=mad,
        robust_scale=robust_scale,
        threshold=threshold,
        sample_count=int(samples.size),
    )


def signed_change_mask(
    delta: np.ndarray,
    *,
    threshold: float,
    direction: Direction,
    valid_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Apply a one-sided threshold to a signed ``after - before`` array."""
    if threshold < 0:
        raise ValueError("Threshold must be non-negative.")
    values = np.asarray(delta, dtype=np.float32)
    finite = np.isfinite(values)
    if valid_mask is not None:
        valid = np.asarray(valid_mask, dtype=bool)
        if valid.shape != values.shape:
            raise ValueError("valid_mask shape must match delta shape.")
        finite &= valid
    if direction == "decrease":
        signed = -values
    elif direction == "increase":
        signed = values
    else:  # pragma: no cover - typing guards callers, runtime guard remains useful
        raise ValueError("direction must be 'decrease' or 'increase'.")
    return finite & (signed >= float(threshold))


def two_sided_change_masks(
    delta: np.ndarray,
    *,
    threshold: float,
    valid_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return decreased- and increased-backscatter masks at one threshold."""
    return (
        signed_change_mask(delta, threshold=threshold, direction="decrease", valid_mask=valid_mask),
        signed_change_mask(delta, threshold=threshold, direction="increase", valid_mask=valid_mask),
    )
