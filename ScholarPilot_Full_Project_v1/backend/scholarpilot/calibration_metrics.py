"""Offline metrics for trust-aware Agent evaluation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class CalibrationObservation:
    confidence: float
    correct: bool
    accepted: bool = True


def expected_calibration_error(
    observations: list[CalibrationObservation],
    *,
    bins: int = 10,
) -> float:
    """Return weighted absolute confidence/accuracy calibration error."""
    if not observations:
        return 0.0
    bins = max(1, bins)
    total = len(observations)
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        bucket = [
            item
            for item in observations
            if lower <= max(0.0, min(1.0, item.confidence))
            < upper
            or (
                index == bins - 1
                and max(0.0, min(1.0, item.confidence)) == 1.0
            )
        ]
        if not bucket:
            continue
        accuracy = sum(item.correct for item in bucket) / len(bucket)
        confidence = sum(
            max(0.0, min(1.0, item.confidence)) for item in bucket
        ) / len(bucket)
        error += len(bucket) / total * abs(accuracy - confidence)
    return error


def brier_score(observations: list[CalibrationObservation]) -> float:
    """Return mean squared probability error (lower is better)."""
    if not observations:
        return 0.0
    return sum(
        (
            max(0.0, min(1.0, item.confidence))
            - (1.0 if item.correct else 0.0)
        )
        ** 2
        for item in observations
    ) / len(observations)


def accuracy_at_coverage(
    observations: list[CalibrationObservation],
) -> list[tuple[float, float]]:
    """Return the selective accuracy curve ordered by confidence."""
    if not observations:
        return []
    ordered = sorted(
        observations,
        key=lambda item: item.confidence,
        reverse=True,
    )
    correct = 0
    total = len(ordered)
    curve: list[tuple[float, float]] = []
    for index, item in enumerate(ordered, start=1):
        correct += int(item.correct)
        curve.append((index / total, correct / index))
    return curve


def selective_accuracy_coverage_auc(
    observations: list[CalibrationObservation],
) -> float:
    """Trapezoidal area under the accuracy/coverage curve."""
    curve = accuracy_at_coverage(observations)
    if not curve:
        return 0.0
    points = [(0.0, curve[0][1]), *curve]
    return sum(
        (right_x - left_x) * (left_y + right_y) / 2.0
        for (left_x, left_y), (right_x, right_y) in zip(
            points,
            points[1:],
        )
    )


def retry_recovery_rate(
    before_correct: list[bool],
    after_correct: list[bool],
) -> float:
    """Fraction of initially wrong cases corrected by bounded recovery."""
    pairs = list(zip(before_correct, after_correct))
    recoverable = [after for before, after in pairs if not before]
    return (
        sum(bool(value) for value in recoverable) / len(recoverable)
        if recoverable
        else 0.0
    )


def abstain_precision(
    observations: list[CalibrationObservation],
) -> float:
    """Fraction of abstained cases that were in fact incorrect."""
    abstained = [item for item in observations if not item.accepted]
    return (
        sum(not item.correct for item in abstained) / len(abstained)
        if abstained
        else 0.0
    )


def intervention_flip_rate(
    baseline_values: list[str],
    intervened_values: list[str],
) -> float:
    """Fraction whose canonical outcome changes under an intervention."""
    pairs = list(zip(baseline_values, intervened_values))
    return (
        sum(left != right for left, right in pairs) / len(pairs)
        if pairs
        else 0.0
    )
