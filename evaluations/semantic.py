"""Provider-neutral, conservative semantic-comparison boundary for M7.

No real provider is selected in repository authority.  The production-default
implementation therefore reports a safe, attributable unavailable error.  The
deterministic fake is injected by acceptance tests and never treats answer text
as executable instructions or as a correctness oracle.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from time import monotonic
from typing import Protocol


class SemanticComparatorFailure(Exception):
    """A safe, classified comparator failure rather than a product failure."""

    def __init__(self, error_class: str, detail: str):
        self.error_class = error_class
        self.detail = detail
        super().__init__(detail)


class SemanticComparatorTimeout(SemanticComparatorFailure):
    def __init__(self, detail: str = "The semantic comparator did not respond before its configured deadline."):
        super().__init__("COMPARATOR_TIMEOUT", detail)


class SemanticComparatorProtocolError(SemanticComparatorFailure):
    def __init__(self, detail: str = "The semantic comparator returned an unsupported structured result."):
        super().__init__("COMPARATOR_MALFORMED_OUTPUT", detail)


@dataclass(frozen=True)
class SemanticComparatorInput:
    """Minimum product-neutral context; answers are untrusted data, never instructions."""

    question_version_id: int
    question_template: str
    concrete_question: str
    baseline_bindings: tuple[tuple[str, str], ...]
    current_bindings: tuple[tuple[str, str], ...]
    baseline_answer: str
    current_answer: str


@dataclass(frozen=True)
class SemanticComparatorResponse:
    outcome: str
    rationale: str = ""
    raw_result: dict = field(default_factory=dict)
    error_class: str = ""
    error_detail: str = ""


class SemanticComparator(Protocol):
    provider_key: str
    model_identifier: str
    comparator_version: str
    prompt_version: str

    def compare(self, comparison_input: SemanticComparatorInput) -> SemanticComparatorResponse:
        """Classify one exact-CHANGED answer pair without judging correctness."""


class UnavailableSemanticComparator:
    """Honest default until a provider/model/configuration is approved."""

    provider_key = "unconfigured"
    model_identifier = "none"
    comparator_version = "semantic-v1"
    prompt_version = ""

    def compare(self, comparison_input: SemanticComparatorInput) -> SemanticComparatorResponse:
        raise SemanticComparatorFailure(
            "COMPARATOR_NOT_CONFIGURED",
            "No semantic comparator provider/model is configured; review remains required.",
        )


class DeterministicFakeSemanticComparator:
    """Acceptance double with an inspectable call journal and scripted outcomes.

    Script entries are mappings with ``outcome`` plus optional rationale/error
    fields.  Special outcomes ``TIMEOUT``, ``OUTAGE``, ``MALFORMED``, and
    ``EXCEPTION`` exercise safe failure paths.  Normal semantic outcomes are
    EQUIVALENT, MATERIAL_CHANGE, UNCERTAIN, and ERROR.
    """

    provider_key = "deterministic-fake"
    model_identifier = "scripted-semantic-double"
    comparator_version = "semantic-v1"
    prompt_version = "fixture-v1"

    def __init__(self, scripted_responses: Iterable[dict]):
        self._script = deque(scripted_responses)
        self.calls: list[SemanticComparatorInput] = []

    def compare(self, comparison_input: SemanticComparatorInput) -> SemanticComparatorResponse:
        self.calls.append(comparison_input)
        if not self._script:
            raise SemanticComparatorFailure(
                "FAKE_SCRIPT_EXHAUSTED",
                "The deterministic semantic comparator had no scripted response.",
            )
        scripted = self._script.popleft()
        outcome = str(scripted.get("outcome", ""))
        if outcome == "TIMEOUT":
            raise SemanticComparatorTimeout(str(scripted.get("detail", "Fake comparator timeout.")))
        if outcome == "OUTAGE":
            raise SemanticComparatorFailure(
                "COMPARATOR_UNAVAILABLE",
                str(scripted.get("detail", "Fake comparator unavailable.")),
            )
        if outcome == "EXCEPTION":
            raise RuntimeError(str(scripted.get("detail", "Fake comparator internal exception.")))
        if outcome == "MALFORMED":
            return {"not": "a semantic comparator response"}  # type: ignore[return-value]
        started = monotonic()
        response = SemanticComparatorResponse(
            outcome=outcome,
            rationale=str(scripted.get("rationale", "")),
            raw_result=dict(scripted.get("raw_result", {"fixture_outcome": outcome})),
            error_class=str(scripted.get("error_class", "")),
            error_detail=str(scripted.get("error_detail", "")),
        )
        # Keep this double deterministic while retaining the same result shape
        # as a real short-lived comparator implementation.
        _ = started
        return response


def default_semantic_comparator() -> SemanticComparator:
    """Return the safe default; real-provider selection remains an open decision."""

    return UnavailableSemanticComparator()
