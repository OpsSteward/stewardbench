import hashlib
from dataclasses import asdict

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.policy import require_admin
from catalog.models import Domain, Question, Tag
from catalog.services import create_domain, create_question, create_tag

from .models import (
    ImportedSourceCell,
    ImportedSourceRow,
    ImportWarning,
    LegacyImportBatch,
    LegacyObservation,
)
from .workbook import IMPORTER_VERSION


class CorpusImportConflict(Exception):
    def __init__(self, report):
        self.report = report
        super().__init__("Source conflicts require manual reconciliation before apply.")


def _domain_conflicts_and_status(plan):
    slugs = [domain.slug for domain in plan.domains]
    names = [domain.name for domain in plan.domains]
    existing = list(Domain.objects.filter(Q(slug__in=slugs) | Q(name__in=names)))
    conflicts = []
    status = {}
    for domain in plan.domains:
        slug_matches = [item for item in existing if item.slug == domain.slug]
        name_matches = [item for item in existing if item.name == domain.name]
        exact = [
            item for item in existing
            if item.slug == domain.slug and item.name == domain.name
        ]
        if exact:
            status[domain.slug] = "REUSED"
        elif slug_matches or name_matches:
            conflict = (slug_matches or name_matches)[0]
            conflicts.append(
                {
                    "code": "SOURCE_CONFLICT",
                    "object": f"Domain {domain.slug}",
                    "explanation": (
                        f"Approved domain {domain.name!r}/{domain.slug!r} conflicts with "
                        f"existing {conflict.name!r}/{conflict.slug!r}."
                    ),
                }
            )
            status[domain.slug] = "CONFLICT"
        else:
            status[domain.slug] = "CREATE"
    return conflicts, status


def _tag_conflicts_and_status(plan):
    existing = set(Tag.objects.filter(name__in=plan.tags).values_list("name", flat=True))
    return {name: "REUSED" if name in existing else "CREATE" for name in plan.tags}


def _question_conflicts_and_status(plan):
    stable_ids = [question.stable_id for question in plan.questions]
    existing = {
        question.stable_id: question
        for question in Question.objects.filter(stable_id__in=stable_ids)
        .select_related("domain")
        .prefetch_related("versions", "tags")
    }
    conflicts = []
    status = {}
    for expected in plan.questions:
        question = existing.get(expected.stable_id)
        if question is None:
            status[expected.stable_id] = "CREATE"
            continue
        current = next(
            (version for version in question.versions.all() if version.valid_to is None),
            None,
        )
        actual_tags = {tag.name for tag in question.tags.all()}
        safe = (
            question.kind == Question.Kind.SINGLE_TURN
            and question.domain is not None
            and question.domain.slug == expected.domain_slug
            and current is not None
            and current.question_text == expected.question_text
            and set(expected.tags).issubset(actual_tags)
        )
        if safe:
            status[expected.stable_id] = "REUSED"
        else:
            status[expected.stable_id] = "CONFLICT"
            conflicts.append(
                {
                    "code": "SOURCE_CONFLICT",
                    "object": f"Question {expected.stable_id}",
                    "explanation": (
                        "Existing Question does not exactly match the approved imported "
                        "kind, current text, domain, and required deterministic tags; "
                        "it was not changed."
                    ),
                }
            )
    return conflicts, status


def reconcile_import(plan):
    existing_batch = LegacyImportBatch.objects.filter(
        mapping_identifier=plan.mapping.identifier,
        mapping_version=plan.mapping.version,
        source_sha256=plan.source_sha256,
    ).first()
    domain_conflicts, domain_status = _domain_conflicts_and_status(plan)
    tag_status = _tag_conflicts_and_status(plan)
    question_conflicts, question_status = _question_conflicts_and_status(plan)
    conflicts = domain_conflicts + question_conflicts

    if existing_batch:
        created_domains = 0
        reused_domains = len(plan.domains)
        created_tags = 0
        reused_tags = len(plan.tags)
        created_questions = 0
        reused_questions = len(plan.questions)
        created_observations = 0
        reused_observations = len(plan.observations)
        created_source_rows = 0
        reused_source_rows = len(plan.source_rows)
        created_source_cells = 0
        reused_source_cells = sum(len(row.cells) for row in plan.source_rows)
        created_warnings = 0
        reused_warnings = len(plan.warnings)
    else:
        created_domains = sum(value == "CREATE" for value in domain_status.values())
        reused_domains = sum(value == "REUSED" for value in domain_status.values())
        created_tags = sum(value == "CREATE" for value in tag_status.values())
        reused_tags = sum(value == "REUSED" for value in tag_status.values())
        created_questions = sum(value == "CREATE" for value in question_status.values())
        reused_questions = sum(value == "REUSED" for value in question_status.values())
        created_observations = len(plan.observations)
        reused_observations = 0
        created_source_rows = len(plan.source_rows)
        reused_source_rows = 0
        created_source_cells = sum(len(row.cells) for row in plan.source_rows)
        reused_source_cells = 0
        created_warnings = len(plan.warnings)
        reused_warnings = 0

    target_count = sum(
        question.source_role == "TARGET_QUESTIONS" for question in plan.questions
    )
    random_count = sum(
        question.source_role == "RANDOM_GENERALIZATION" for question in plan.questions
    )
    kb_count = sum(question.source_role == "KB_RAG" for question in plan.questions)
    sheet_report = {
        sheet_name: dict(values) for sheet_name, values in plan.inventory.items()
    }
    sheet_report["Interface Issues"]["ignored_meaningful_rows"] = sheet_report[
        "Interface Issues"
    ]["meaningful_rows"]
    domain_report = []
    for domain in plan.domains:
        item = asdict(domain)
        item["reconciliation"] = domain_status[domain.slug]
        domain_report.append(item)
    question_report = []
    for question in plan.questions:
        item = asdict(question)
        item["reconciliation"] = question_status[question.stable_id]
        question_report.append(item)
    observation_report = [asdict(observation) for observation in plan.observations]
    source_row_report = [
        {
            "sheet_name": source.sheet_name,
            "source_row_number": source.row_number,
            "classification": source.classification,
            "interpretation_source": source.interpretation_source,
            "structural_kind": source.structural_kind,
            "domain_slug": source.domain_slug,
            "question_stable_id": source.question_stable_id,
            "source_fingerprint": source.source_fingerprint,
        }
        for source in plan.source_rows
    ]
    summary = {
        "physical_rows": sum(sheet["physical_rows"] for sheet in sheet_report.values()),
        "meaningful_rows": sum(
            sheet["meaningful_rows"] for sheet in sheet_report.values()
        ),
        "header_rows": sum(sheet["header_rows"] for sheet in sheet_report.values()),
        "blank_or_separator_rows": sum(
            sheet["blank_rows"] for sheet in sheet_report.values()
        ),
        "canonical_questions": len(plan.questions),
        "target_canonical_questions": target_count,
        "random_canonical_questions": random_count,
        "kb_rag_canonical_questions": kb_count,
        "question_versions": len(plan.questions),
        "legacy_observations": len(plan.observations),
        "domains": len(plan.domains),
        "tags": len(plan.tags),
        "binding_definitions": 0,
        "historical_fixtures": 0,
        "source_rows": len(plan.source_rows),
        "source_cells": sum(len(row.cells) for row in plan.source_rows),
        "warnings": len(plan.warnings),
        "manual_review_items": len(plan.warnings),
        "ignored_interface_issue_rows": plan.inventory["Interface Issues"][
            "meaningful_rows"
        ],
        "target_separator_rows": len(
            plan.inventory["target questions"]["separator_rows"]
        ),
        "conflicts": len(conflicts),
    }
    changes = {
        "domains_created": created_domains,
        "domains_reused": reused_domains,
        "tags_created": created_tags,
        "tags_reused": reused_tags,
        "questions_created": created_questions,
        "questions_reused": reused_questions,
        "question_versions_created": created_questions,
        "question_versions_reused": reused_questions,
        "legacy_observations_created": created_observations,
        "legacy_observations_reused": reused_observations,
        "source_rows_created": created_source_rows,
        "source_rows_reused": reused_source_rows,
        "source_cells_created": created_source_cells,
        "source_cells_reused": reused_source_cells,
        "warnings_created": created_warnings,
        "warnings_reused": reused_warnings,
        "records_skipped": summary["ignored_interface_issue_rows"]
        + summary["blank_or_separator_rows"],
    }
    return {
        "mode": "DRY_RUN",
        "mapping": {
            "name": plan.mapping.name,
            "identifier": plan.mapping.identifier,
            "version": plan.mapping.version,
            "fixture_sha256": plan.mapping.fingerprint,
        },
        "source": {
            "filename": plan.source_filename,
            "sha256": plan.source_sha256,
            "size_bytes": plan.source_size_bytes,
            "metadata": plan.source_metadata,
        },
        "already_applied": bool(existing_batch),
        "existing_batch_id": existing_batch.pk if existing_batch else None,
        "sheets": sheet_report,
        "domains": domain_report,
        "tags": [
            {"name": name, "reconciliation": tag_status[name]} for name in plan.tags
        ],
        "questions": question_report,
        "legacy_observations": observation_report,
        "source_rows": source_row_report,
        "summary": summary,
        "changes": changes,
        "warnings": [asdict(warning) for warning in plan.warnings],
        "conflicts": conflicts,
        "fatal": bool(conflicts),
    }


def _advisory_lock_key(plan):
    identity = f"{plan.mapping.identifier}:{plan.mapping.version}:{plan.source_sha256}"
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


@transaction.atomic
def apply_import(*, plan, actor):
    require_admin(actor)
    if connection.vendor != "postgresql":
        raise ValidationError("StewardBench corpus import requires PostgreSQL.")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_advisory_lock_key(plan)])

    existing_batch = LegacyImportBatch.objects.filter(
        mapping_identifier=plan.mapping.identifier,
        mapping_version=plan.mapping.version,
        source_sha256=plan.source_sha256,
    ).first()
    if existing_batch:
        report = reconcile_import(plan)
        report["mode"] = "APPLY"
        report["applied"] = False
        report["batch_id"] = existing_batch.pk
        return report

    report = reconcile_import(plan)
    if report["conflicts"]:
        raise CorpusImportConflict(report)

    imported_at = timezone.now()
    domains = {}
    for expected in plan.domains:
        domain = Domain.objects.filter(slug=expected.slug, name=expected.name).first()
        if domain is None:
            domain = create_domain(
                actor=actor,
                slug=expected.slug,
                name=expected.name,
                description="",
                is_active=True,
            )
        domains[expected.slug] = domain

    tags = {}
    for name in plan.tags:
        tag = Tag.objects.filter(name=name).first()
        if tag is None:
            tag = create_tag(actor=actor, name=name)
        tags[name] = tag

    questions = {}
    versions = {}
    for expected in plan.questions:
        question = Question.objects.filter(stable_id=expected.stable_id).first()
        if question is None:
            question = create_question(
                actor=actor,
                stable_id=expected.stable_id,
                kind=Question.Kind.SINGLE_TURN,
                lifecycle=Question.Lifecycle.DRAFT,
                domain=domains[expected.domain_slug],
                tags=[tags[name] for name in expected.tags],
                rationale="",
                question_text=expected.question_text,
                evaluation_guidance="",
                bindings=(),
            )
        questions[expected.stable_id] = question
        versions[expected.stable_id] = question.current_version

    batch = LegacyImportBatch.objects.create(
        mapping_identifier=plan.mapping.identifier,
        mapping_name=plan.mapping.name,
        mapping_version=plan.mapping.version,
        importer_version=IMPORTER_VERSION,
        source_filename=plan.source_filename,
        source_sha256=plan.source_sha256,
        source_size_bytes=plan.source_size_bytes,
        source_metadata=plan.source_metadata,
        workbook_inventory=plan.inventory,
        mapping_snapshot=plan.mapping.data,
        reconciliation_counts={
            "summary": report["summary"],
            "changes": report["changes"],
        },
        imported_at=imported_at,
        imported_by=actor,
    )

    row_records = {}
    cell_records = []
    for source in plan.source_rows:
        question = questions.get(source.question_stable_id)
        row_record = ImportedSourceRow.objects.create(
            batch=batch,
            sheet_name=source.sheet_name,
            source_row_number=source.row_number,
            source_role=source.source_role,
            classification=source.classification,
            interpretation_source=source.interpretation_source,
            structural_kind=source.structural_kind,
            source_fingerprint=source.source_fingerprint,
            mapping_context=source.mapping_context,
            domain=domains.get(source.domain_slug),
            question=question,
            question_version=(
                versions.get(source.question_stable_id) if question is not None else None
            ),
        )
        row_records[(source.sheet_name, source.row_number)] = row_record
        for cell in source.cells:
            cell_records.append(
                ImportedSourceCell(
                    source_row=row_record,
                    coordinate=cell.coordinate,
                    column_name=cell.column_name,
                    data_type=cell.data_type,
                    raw_value=cell.raw_value,
                    displayed_value=cell.displayed_value,
                    formula=cell.formula,
                )
            )
    ImportedSourceCell.objects.bulk_create(cell_records)

    legacy_rules = plan.mapping.data["legacy_observation"]
    for observation in plan.observations:
        question = questions.get(observation.question_stable_id)
        LegacyObservation.objects.create(
            source_row=row_records[(observation.sheet_name, observation.row_number)],
            question=question,
            question_version=(
                versions.get(observation.question_stable_id) if question is not None else None
            ),
            source_question_text=observation.source_question_text,
            observed_answer_text=observation.observed_answer_text,
            answer_fidelity=legacy_rules["answer_fidelity"],
            legacy_expectation=observation.legacy_expectation,
            expected_answer_role=legacy_rules["expected_answer_role"],
            acceptable_source_value=observation.acceptable_source_value,
            legacy_judgment=observation.legacy_judgment,
            judgment_source=legacy_rules["judgment_source"],
            comments=observation.comments,
            secondary_comments=observation.secondary_comments,
            experiment_metadata=observation.experiment_metadata,
            unknown_metadata=legacy_rules["unknown_metadata"],
            imported_at=imported_at,
        )
    ImportWarning.objects.bulk_create(
        [
            ImportWarning(
                batch=batch,
                sheet_name=warning.sheet_name,
                source_rows=list(warning.source_rows),
                code=warning.code,
                explanation=warning.explanation,
            )
            for warning in plan.warnings
        ]
    )
    final_source_sha256 = hashlib.sha256(plan.source_path.read_bytes()).hexdigest()
    if final_source_sha256 != plan.source_sha256:
        raise ValidationError(
            "The source workbook changed during import; all database changes were rolled back."
        )
    report["mode"] = "APPLY"
    report["applied"] = True
    report["batch_id"] = batch.pk
    return report
