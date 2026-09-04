from decimal import Decimal

import pytest

from evaluations.adapters import normalized_telemetry
from evaluations.performance import classify_latency, performance_comparison, token_delta
from evaluations.reporting import percentile


@pytest.mark.parametrize(
    ("latency_ms", "expected"),
    [(999, "TARGET"), (1000, "TARGET"), (1001, "GOOD"), (2000, "GOOD"), (2001, "ACCEPTABLE"), (5000, "ACCEPTABLE"), (5001, "SLOW"), (10000, "SLOW"), (10001, "BAD")],
)
def test_acc_perf_001_policy_boundaries(latency_ms, expected):
    assert classify_latency(latency_ms) == expected


@pytest.mark.parametrize(
    ("baseline", "current", "state", "degraded"),
    [(8000, 10000, "REGRESSED", False), (100, 130, "STABLE", False), (8000, 9500, "STABLE", False), (9000, 3000, "IMPROVED", False), (4900, 5100, "STABLE", True), (1200, 1700, "REGRESSED", False)],
)
def test_acc_perf_002_controlled_latency_rules(baseline, current, state, degraded):
    result = performance_comparison(baseline, current)
    assert result["state"] == state
    assert result["band_degraded"] is degraded


@pytest.mark.parametrize(
    ("baseline", "current", "delta", "percent", "baseline_band", "current_band", "state"),
    [
        (8000, 10000, 2000, Decimal("25.00"), "SLOW", "SLOW", "REGRESSED"),
        (100, 130, 30, Decimal("30.00"), "TARGET", "TARGET", "STABLE"),
        (8000, 9500, 1500, Decimal("18.75"), "SLOW", "SLOW", "STABLE"),
        (9000, 3000, -6000, Decimal("-66.67"), "SLOW", "ACCEPTABLE", "IMPROVED"),
        (1200, 1700, 500, Decimal("41.67"), "GOOD", "GOOD", "REGRESSED"),
        (4900, 5100, 200, Decimal("4.08"), "ACCEPTABLE", "SLOW", "STABLE"),
    ],
)
def test_acc_perf_002_raw_deltas_and_bands_are_auditable(baseline, current, delta, percent, baseline_band, current_band, state):
    result = performance_comparison(baseline, current)
    assert result == {
        "baseline_latency_ms": baseline,
        "current_latency_ms": current,
        "latency_delta_ms": delta,
        "latency_delta_percent": percent,
        "baseline_band": baseline_band,
        "current_band": current_band,
        "state": state,
        "band_degraded": current_band in {"SLOW"} and baseline_band == "ACCEPTABLE",
    }


def test_acc_eff_001_target_reported_telemetry_is_explicit_and_optional():
    telemetry = normalized_telemetry(
        {"metadata": {"telemetry": {"usage": {"input_tokens": 1000, "output_tokens": 2000, "total_tokens": 3000, "reasoning_tokens": 2}, "runtime": {"provider_or_runtime": "vLLM", "model": "synthetic-model"}, "internal_timings": {"routing_ms": 4.5}}}}
    )
    assert telemetry["input_tokens"] == 1000
    assert telemetry["output_tokens"] == 2000
    assert telemetry["total_tokens"] == 3000
    assert telemetry["runtime_telemetry"] == {"provider_or_runtime": "vLLM", "model": "synthetic-model"}
    assert telemetry["internal_timing_metadata"] == {"routing_ms": 4.5}
    assert normalized_telemetry({"metadata": {"telemetry": {"usage": {"total_tokens": -1}}}})["total_tokens"] is None
    assert token_delta(3000, 2000) == (-1000, Decimal("-33.33"))
    assert token_delta(3000, None) == (None, None)
    assert token_delta(None, 2000) == (None, None)


def test_acc_perf_001_nearest_rank_percentiles_are_centralized():
    """The dashboard/run/export projection uses one documented small-sample rule."""

    values = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
    assert (percentile(values, 0.50), percentile(values, 0.90), percentile(values, 0.95)) == (500, 900, 1000)
