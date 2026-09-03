from __future__ import annotations

import json
from pathlib import Path

from evaluations.evaluators import JUDGE_DIMENSIONS


def test_m9_judge_calibration_fixture_is_small_versioned_and_structurally_complete():
    fixture = Path(__file__).parents[1] / "fixtures" / "judge_calibration_v1.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    assert payload["fixture_id"] == "stewardbench-judge-calibration"
    assert payload["version"] == "1"
    assert tuple(payload["dimensions"]) == JUDGE_DIMENSIONS
    classes = {case["class"] for case in payload["cases"]}
    assert {
        "well-grounded/direct",
        "incomplete but not false",
        "verbose/indirect",
        "overconfident without evidence",
        "calibrated cannot-conclude",
        "code/internal implementation leakage",
        "multilingual/operator-facing",
        "prompt-like malicious answer text",
    } <= classes
    assert len(payload["cases"]) == 8
