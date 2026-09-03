import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from django.core.exceptions import ValidationError


EXPECTED_MAPPING_NAME = "StewardBench workbook mapping v1"
EXPECTED_MAPPING_IDENTIFIER = "v2-dev-troubleshooting-v1"
EXPECTED_MAPPING_VERSION = 1


@dataclass(frozen=True)
class MappingFixture:
    path: Path
    data: dict
    fingerprint: str

    @property
    def name(self):
        return self.data["mapping_name"]

    @property
    def identifier(self):
        return self.data["mapping_identifier"]

    @property
    def version(self):
        return self.data["mapping_version"]

    @property
    def expected_sha256(self):
        return self.data["expected_workbook_sha256"]


def _require(condition, message):
    if not condition:
        raise ValidationError(message)


def load_mapping(path):
    mapping_path = Path(path)
    raw = mapping_path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"Invalid UTF-8 JSON mapping fixture: {error}") from error

    _require(data.get("mapping_name") == EXPECTED_MAPPING_NAME, "Unexpected mapping name.")
    _require(
        data.get("mapping_identifier") == EXPECTED_MAPPING_IDENTIFIER,
        "Unexpected mapping identifier.",
    )
    _require(data.get("mapping_version") == EXPECTED_MAPPING_VERSION, "Mapping version must be 1.")
    expected_sha = data.get("expected_workbook_sha256", "")
    _require(
        len(expected_sha) == 64
        and expected_sha == expected_sha.lower()
        and all(character in "0123456789abcdef" for character in expected_sha),
        "Mapping workbook SHA-256 is invalid.",
    )

    expected_sheets = [
        "known questions",
        "knowledge base - rag questions",
        "Interface Issues",
        "random question",
        "target questions",
    ]
    _require(
        data.get("recognized_sheets") == expected_sheets,
        "Recognized sheets must match exactly.",
    )
    sheets = data.get("sheets", {})
    _require(list(sheets) == expected_sheets, "Sheet mapping order must match workbook order.")
    _require(
        sheets["Interface Issues"].get("role") == "IGNORED",
        "Interface Issues must be ignored.",
    )

    target = sheets["target questions"]
    domains = target.get("domains", [])
    _require(len(domains) == 16, "Target mapping must contain exactly 16 domains.")
    codes = [domain.get("code") for domain in domains]
    names = [domain.get("name") for domain in domains]
    slugs = [domain.get("slug") for domain in domains]
    _require(len(set(codes)) == 16, "Target domain codes must be unique.")
    _require(len(set(names)) == 16, "Target domain names must be unique.")
    _require(len(set(slugs)) == 16, "Target domain slugs must be unique.")
    _require(
        target.get("domain_interpretation_source") == "PRODUCT_OWNER_MAPPING",
        "Target domain taxonomy must identify product-owner mapping provenance.",
    )
    _require(
        [(domain["start_row"], domain["end_row"]) for domain in domains]
        == [
            (2, 6),
            (8, 17),
            (19, 25),
            (27, 36),
            (38, 48),
            (50, 63),
            (65, 76),
            (78, 87),
            (89, 104),
            (106, 115),
            (117, 129),
            (131, 141),
            (143, 156),
            (158, 166),
            (168, 182),
            (184, 202),
        ],
        "Target domain row ranges do not match approved mapping v1.",
    )
    _require(
        target.get("separator_rows")
        == [7, 18, 26, 37, 49, 64, 77, 88, 105, 116, 130, 142, 157, 167, 183],
        "Target separator rows do not match the source inventory.",
    )
    merge_rules = target.get("merge_rules", [])
    _require(len(merge_rules) == 1, "Mapping v1 must contain exactly one merge rule.")
    _require(
        merge_rules[0].get("source_rows") == [155, 156]
        and merge_rules[0].get("canonical_text")
        == (
            "Which validation findings affect this device, interface, adjacency, "
            "service, or infrastructure segment?"
        ),
        "The approved rows 155-156 merge rule is missing or altered.",
    )
    _require(
        target.get("conversation_grouping_deferred_rows") == [193, 202],
        "Conversation-deferred range must be rows 193-202.",
    )

    random_mapping = sheets["random question"]
    _require(
        (random_mapping.get("domain_name"), random_mapping.get("domain_code"))
        == ("Generalization", "GEN"),
        "Random questions must map to Generalization/GEN.",
    )
    normalization = data.get("legacy_observation", {}).get("acceptable_normalization")
    _require(
        normalization == {"Yes": "GOOD", "No": "BAD", "NO": "BAD"},
        "Legacy Acceptable normalization differs from approved mapping v1.",
    )
    return MappingFixture(
        path=mapping_path,
        data=data,
        fingerprint=hashlib.sha256(raw).hexdigest(),
    )
