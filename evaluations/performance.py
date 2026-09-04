"""Versioned, product-neutral performance evidence helpers.

The thresholds deliberately classify only StewardBench's immutable, externally
observed request latency.  They do not judge answer quality or target-internal
telemetry.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


PERFORMANCE_POLICY_VERSION = "opss-performance-v1"
PERFORMANCE_BANDS = ("TARGET", "GOOD", "ACCEPTABLE", "SLOW", "BAD")
PERFORMANCE_STATES = ("IMPROVED", "STABLE", "REGRESSED", "UNKNOWN")


def classify_latency(latency_ms: int | None) -> str | None:
    """Return the v1 band for a completed response, using integer ms only."""

    if latency_ms is None:
        return None
    if latency_ms <= 1000:
        return "TARGET"
    if latency_ms <= 2000:
        return "GOOD"
    if latency_ms <= 5000:
        return "ACCEPTABLE"
    if latency_ms <= 10000:
        return "SLOW"
    return "BAD"


def latency_percent_delta(baseline_ms: int | None, current_ms: int | None) -> Decimal | None:
    if baseline_ms is None or current_ms is None or baseline_ms <= 0:
        return None
    return ((Decimal(current_ms - baseline_ms) * Decimal("100")) / Decimal(baseline_ms)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def performance_comparison(baseline_ms: int | None, current_ms: int | None) -> dict[str, object]:
    """Compute transparent controlled-pair evidence without a composite score."""

    baseline_band = classify_latency(baseline_ms)
    current_band = classify_latency(current_ms)
    if baseline_ms is None or current_ms is None:
        return {
            "baseline_latency_ms": baseline_ms,
            "current_latency_ms": current_ms,
            "latency_delta_ms": None,
            "latency_delta_percent": None,
            "baseline_band": baseline_band,
            "current_band": current_band,
            "state": "UNKNOWN",
            "band_degraded": False,
        }
    delta = current_ms - baseline_ms
    percent = latency_percent_delta(baseline_ms, current_ms)
    # A performance regression requires both approved relative and absolute
    # evidence. Improvements remain visible whenever the raw latency improves.
    regressed = delta >= 500 and percent is not None and percent >= Decimal("25")
    state = "REGRESSED" if regressed else "IMPROVED" if delta < 0 else "STABLE"
    order = {band: index for index, band in enumerate(PERFORMANCE_BANDS)}
    return {
        "baseline_latency_ms": baseline_ms,
        "current_latency_ms": current_ms,
        "latency_delta_ms": delta,
        "latency_delta_percent": percent,
        "baseline_band": baseline_band,
        "current_band": current_band,
        "state": state,
        "band_degraded": bool(baseline_band and current_band and order[current_band] > order[baseline_band]),
    }


def token_delta(baseline: int | None, current: int | None) -> tuple[int | None, Decimal | None]:
    if baseline is None or current is None:
        return None, None
    return current - baseline, latency_percent_delta(baseline, current)
