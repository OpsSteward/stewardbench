import hashlib
import json

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError

from corpus.mapping import load_mapping


MAPPING_PATH = settings.BASE_DIR / "import_mappings/v2_dev_troubleshooting_v1.json"
CONVERSATION_MAPPING_PATH = settings.BASE_DIR / "import_mappings/conversation_scenarios_v1.json"
WORKBOOK_PATH = settings.BASE_DIR / "docs/reference/v2-dev-troubleshooting.xlsx"


EXPECTED_DOMAINS = [
    (2, 6, "Service Traversal", "TRAV"),
    (8, 17, "L0 Topology", "L0"),
    (19, 25, "L1 Topology", "L1"),
    (27, 36, "L2 Topology", "L2"),
    (38, 48, "L3 Topology", "L3"),
    (50, 63, "Vera Rubin / Rubin LHN", "RUBIN"),
    (65, 76, "Disjointness", "DISJ"),
    (78, 87, "Capacity and Resource Sharing", "CAP"),
    (89, 104, "Blast Radius", "BLAST"),
    (106, 115, "Power", "POWER"),
    (117, 129, "Temporal / Historical Reasoning", "TEMP"),
    (131, 141, "Root-Cause Analysis", "RCA"),
    (143, 156, "Provenance and Validation", "PROV"),
    (158, 166, "Documentation / RAG / MOPs", "DOC"),
    (168, 182, "Visualization", "VIZ"),
    (184, 202, "Service Profiles and Conversational Follow-ups", "PROFILE"),
]


def test_mapping_v1_encodes_all_approved_source_owner_decisions():
    mapping = load_mapping(MAPPING_PATH)
    target = mapping.data["sheets"]["target questions"]

    assert mapping.name == "StewardBench workbook mapping v1"
    assert mapping.identifier == "v2-dev-troubleshooting-v1"
    assert mapping.version == 1
    assert mapping.expected_sha256 == hashlib.sha256(WORKBOOK_PATH.read_bytes()).hexdigest()
    assert mapping.data["recognized_sheets"] == [
        "known questions",
        "knowledge base - rag questions",
        "Interface Issues",
        "random question",
        "target questions",
    ]
    assert mapping.data["sheets"]["Interface Issues"]["role"] == "IGNORED"
    assert [
        (item["start_row"], item["end_row"], item["name"], item["code"])
        for item in target["domains"]
    ] == EXPECTED_DOMAINS
    assert target["domain_interpretation_source"] == "PRODUCT_OWNER_MAPPING"
    assert target["separator_rows"] == [
        7, 18, 26, 37, 49, 64, 77, 88, 105, 116, 130, 142, 157, 167, 183
    ]
    assert target["merge_rules"] == [
        {
            "source_rows": [155, 156],
            "join_with": " ",
            "canonical_text": (
                "Which validation findings affect this device, interface, adjacency, "
                "service, or infrastructure segment?"
            ),
        }
    ]
    assert target["conversation_grouping_deferred_rows"] == [193, 202]
    assert (
        mapping.data["sheets"]["random question"]["domain_name"],
        mapping.data["sheets"]["random question"]["domain_code"],
    ) == ("Generalization", "GEN")
    assert mapping.data["legacy_observation"]["acceptable_normalization"] == {
        "Yes": "GOOD",
        "No": "BAD",
        "NO": "BAD",
    }
    assert mapping.data["legacy_observation"]["acceptable_unknown_values"] == [
        None,
        "",
        "Partially",
        "Partialy.",
        "Yes for now. ",
    ]


def test_mapping_change_without_version_change_is_rejected(tmp_path):
    data = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    data["sheets"]["target questions"]["separator_rows"] = []
    changed = tmp_path / "mapping.json"
    changed.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValidationError, match="separator rows"):
        load_mapping(changed)


def test_conversation_mapping_v1_uses_only_the_explicit_blueprint_session():
    """M8 must not silently extend the approved six-turn source grouping."""

    mapping = json.loads(CONVERSATION_MAPPING_PATH.read_text(encoding="utf-8"))

    assert mapping["mapping_version"] == "conversation-scenarios-v1"
    assert mapping["source_workbook"] == "docs/reference/v2-dev-troubleshooting.xlsx"
    assert mapping["source_checksum_sha256"] == hashlib.sha256(WORKBOOK_PATH.read_bytes()).hexdigest()
    assert mapping["scenarios"] == [
        {
            "stable_id": "RUBIN-CONV-01",
            "name": "Rubin desired-state EVC follow-up",
            "definition_version": 1,
            "source_authority": "docs/reference/OPSS_EVALUATION_LAB_BLUEPRINT.md section 14",
            "turns": [
                {
                    "ordinal": ordinal,
                    "canonical_question_id": question_id,
                    "source_sheet": "target questions",
                    "source_row": source_row,
                    "required_for_overall": True,
                }
                for ordinal, question_id, source_row in [
                    (1, "PROFILE-004", 187),
                    (2, "PROFILE-007", 190),
                    (3, "PROFILE-010", 193),
                    (4, "PROFILE-011", 194),
                    (5, "PROFILE-012", 195),
                    (6, "PROFILE-013", 196),
                ]
            ],
        }
    ]
    assert mapping["unresolved_rows"] == [
        {
            "source_sheet": "target questions",
            "source_rows": [197, 198, 199, 200, 201, 202],
            "warning": "CONVERSATION_GROUPING_DEFERRED",
            "reason": (
                "The workbook supplies no scenario/session metadata. The retained blueprint explicitly demonstrates only "
                "rows 187, 190, and 193-196; it does not settle whether rows 197-202 extend that session, begin "
                "another session, or remain standalone. Product-owner grouping/turn-order approval is required."
            ),
        }
    ]
