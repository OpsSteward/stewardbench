from collections import Counter
import hashlib

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError

from corpus.mapping import load_mapping
from corpus.workbook import inspect_workbook


MAPPING_PATH = settings.BASE_DIR / "import_mappings/v2_dev_troubleshooting_v1.json"
WORKBOOK_PATH = settings.BASE_DIR / "docs/reference/v2-dev-troubleshooting.xlsx"
EXPECTED_SHA256 = "559ad19500eae888c250c38d3c7213bdf38912d611cd0dbc4dfa2556fa6ec8ff"


@pytest.fixture
def workbook_plan():
    return inspect_workbook(WORKBOOK_PATH, load_mapping(MAPPING_PATH))


def test_real_workbook_inventory_and_source_hash_are_exact(workbook_plan):
    before = hashlib.sha256(WORKBOOK_PATH.read_bytes()).hexdigest()
    assert before == EXPECTED_SHA256 == workbook_plan.source_sha256
    assert workbook_plan.source_metadata == {
        "creator": "Jeronimo Bezerra",
        "last_modified_by": "Jeronimo Bezerra",
        "created": "2026-09-02T14:48:17Z",
        "modified": "2026-09-02T20:59:19Z",
    }
    assert list(workbook_plan.inventory) == [
        "known questions",
        "knowledge base - rag questions",
        "Interface Issues",
        "random question",
        "target questions",
    ]
    assert {
        name: (item["dimension"], item["physical_rows"], item["meaningful_rows"])
        for name, item in workbook_plan.inventory.items()
    } == {
        "known questions": ("A1:E40", 40, 39),
        "knowledge base - rag questions": ("A1:AD57", 57, 4),
        "Interface Issues": ("A1:B18", 18, 17),
        "random question": ("A1:E27", 27, 13),
        "target questions": ("A1:A202", 202, 186),
    }
    assert sum(item["physical_rows"] for item in workbook_plan.inventory.values()) == 344
    assert sum(item["meaningful_rows"] for item in workbook_plan.inventory.values()) == 259
    assert sum(item["blank_rows"] for item in workbook_plan.inventory.values()) == 81
    assert workbook_plan.inventory["Interface Issues"]["ignored_meaningful_rows"] == 17
    assert hashlib.sha256(WORKBOOK_PATH.read_bytes()).hexdigest() == before


def test_parser_reconciles_questions_rows_observations_and_warnings(workbook_plan):
    assert len(workbook_plan.questions) == 199
    assert Counter(question.source_role for question in workbook_plan.questions) == {
        "TARGET_QUESTIONS": 185,
        "RANDOM_GENERALIZATION": 13,
        "KB_RAG": 1,
    }
    assert len(workbook_plan.domains) == 18
    assert len(workbook_plan.observations) == 56
    assert len(workbook_plan.source_rows) == 257
    assert sum(len(row.cells) for row in workbook_plan.source_rows) == 489
    assert len(workbook_plan.warnings) == 62
    assert Counter(warning.code for warning in workbook_plan.warnings) == {
        "POTENTIAL_BINDING_REQUIRES_REVIEW": 53,
        "AMBIGUOUS_CANONICAL_LINK": 4,
        "LEGACY_METADATA_UNKNOWN": 3,
        "CONVERSATION_GROUPING_DEFERRED": 1,
        "UNSUPPORTED_SOURCE_FIELD": 1,
    }
    ambiguous = {
        (warning.sheet_name, warning.source_rows)
        for warning in workbook_plan.warnings
        if warning.code == "AMBIGUOUS_CANONICAL_LINK"
    }
    assert ambiguous == {
        ("known questions", (24, 25)),
        ("known questions", (32, 33)),
        ("known questions", (27,)),
        ("random question", (4,)),
    }

    split = next(
        question
        for question in workbook_plan.questions
        if question.stable_id == "PROV-013"
    )
    assert split.source_rows == (155, 156)
    assert split.question_text == (
        "Which validation findings affect this device, interface, adjacency, service, "
        "or infrastructure segment?"
    )
    assert not any(question.source_rows == (156,) for question in workbook_plan.questions)
    assert next(
        question.question_text
        for question in workbook_plan.questions
        if question.stable_id == "GEN-006"
    ) == "Quantos transceivers no total estão em uso?"


def test_target_domains_have_deterministic_derived_counts_and_ids(workbook_plan):
    target_domains = [
        domain for domain in workbook_plan.domains if domain.source_sheet == "target questions"
    ]
    assert [domain.question_count for domain in target_domains] == [
        5, 10, 7, 10, 11, 14, 12, 10, 16, 10, 13, 11, 13, 9, 15, 19
    ]
    assert all(
        domain.interpretation_source == "PRODUCT_OWNER_MAPPING"
        for domain in target_domains
    )
    assert (target_domains[0].first_id, target_domains[0].last_id) == (
        "TRAV-001",
        "TRAV-005",
    )
    assert (target_domains[-1].first_id, target_domains[-1].last_id) == (
        "PROFILE-001",
        "PROFILE-019",
    )
    assert (target_domains[12].first_id, target_domains[12].last_id) == (
        "PROV-001",
        "PROV-013",
    )


def test_unapproved_workbook_bytes_are_rejected_before_parsing(tmp_path):
    changed = tmp_path / "changed.xlsx"
    changed.write_bytes(WORKBOOK_PATH.read_bytes() + b"changed")

    with pytest.raises(ValidationError, match="SHA-256 mismatch"):
        inspect_workbook(changed, load_mapping(MAPPING_PATH))
