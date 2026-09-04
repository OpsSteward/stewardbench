"""Versioned operator-facing answer representations.

Adapters retain target-specific structured answer fields in immutable Execution
response metadata. This module makes that stored observation available to
comparison, evaluation, export, and safe server-rendered presentation without
asking those product-neutral layers to parse a target wire envelope.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


OPERATOR_ANSWER_METADATA_KEY = "operator_answer"
OPERATOR_ANSWER_SCHEMA_VERSION = "opss-structured-answer-v1"


def structured_operator_answer(response_metadata: object) -> dict[str, Any] | None:
    """Return a stored structured operator answer without reparsing raw output."""

    if not isinstance(response_metadata, Mapping):
        return None
    answer = response_metadata.get(OPERATOR_ANSWER_METADATA_KEY)
    return dict(answer) if isinstance(answer, Mapping) else None


def _normalize_text(value: str) -> str:
    """M6's deliberately shallow, versioned text normalization."""

    return "\n".join(
        line.rstrip(" \t") for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    )


def _normalize_structured_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalize_structured_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_normalize_structured_value(item) for item in value]
    if isinstance(value, str):
        return _normalize_text(value)
    return value


def _canonical_json(value: Any) -> str:
    """A deterministic, data-only representation for comparison/evaluation."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def exact_operator_answer(*, display_answer: str, raw_answer: str, response_metadata: object) -> str:
    """Return the complete answer after exact-v1's shallow normalization.

    Plain-text historical observations deliberately retain their prior exact
    behavior. Structured observations include all source-derived semantic
    fields, including each table cell, in a canonical data representation.
    """

    structured = structured_operator_answer(response_metadata)
    if structured is None:
        return _normalize_text(display_answer or raw_answer)
    return _canonical_json(_normalize_structured_value(structured))


def semantic_operator_answer(*, display_answer: str, raw_answer: str, response_metadata: object) -> str:
    """Return the complete unnormalized answer as untrusted data for evaluators."""

    structured = structured_operator_answer(response_metadata)
    if structured is None:
        return display_answer or raw_answer
    return _canonical_json(structured)


def operator_answer_presentation(response_metadata: object) -> dict[str, Any] | None:
    """Build a safe declarative UI model; target content is never HTML.

    Only the observed ``table`` shape with a rectangular ``columns``/``rows``
    payload receives table markup. Any unknown response kind or malformed table
    is retained and shown as escaped JSON instead of being silently discarded
    or guessed into a different presentation.
    """

    answer = structured_operator_answer(response_metadata)
    if answer is None:
        return None
    payload = answer.get("response_payload")
    columns = payload.get("columns") if isinstance(payload, Mapping) else None
    rows = payload.get("rows") if isinstance(payload, Mapping) else None
    table = None
    if (
        answer.get("response_kind") == "table"
        and isinstance(columns, list)
        and isinstance(rows, list)
        and all(isinstance(row, list) and len(row) == len(columns) for row in rows)
    ):
        table = {"columns": columns, "rows": rows}
    return {
        "answer_type": answer.get("answer_type"),
        "text": answer.get("text", ""),
        "response_kind": answer.get("response_kind"),
        "table": table,
        "fallback_json": json.dumps(answer, ensure_ascii=False, sort_keys=True, indent=2, default=str),
    }
