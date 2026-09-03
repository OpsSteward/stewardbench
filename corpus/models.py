from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from catalog.models import Domain, Question, QuestionVersion


class ImmutableImportRecord(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Imported source evidence is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Imported source evidence cannot be deleted.")


class LegacyImportBatch(ImmutableImportRecord):
    mapping_identifier = models.CharField(max_length=100)
    mapping_name = models.CharField(max_length=160)
    mapping_version = models.PositiveIntegerField()
    importer_version = models.CharField(max_length=40)
    source_filename = models.CharField(max_length=255)
    source_sha256 = models.CharField(max_length=64)
    source_size_bytes = models.PositiveBigIntegerField()
    source_metadata = models.JSONField(default=dict)
    workbook_inventory = models.JSONField(default=dict)
    mapping_snapshot = models.JSONField(default=dict)
    reconciliation_counts = models.JSONField(default=dict)
    imported_at = models.DateTimeField()
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="legacy_import_batches",
    )

    class Meta:
        ordering = ("-imported_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("mapping_identifier", "mapping_version", "source_sha256"),
                name="corpus_batch_source_mapping_unique",
            ),
            models.CheckConstraint(
                condition=Q(source_sha256__regex=r"^[0-9a-f]{64}$"),
                name="corpus_batch_sha256_format",
            ),
            models.CheckConstraint(
                condition=Q(mapping_version__gte=1),
                name="corpus_batch_mapping_version_positive",
            ),
        ]

    def __str__(self):
        return f"{self.mapping_name} ({self.source_sha256[:12]})"


class ImportedSourceRow(ImmutableImportRecord):
    class Classification(models.TextChoices):
        QUESTION_DEFINITION = "QUESTION_DEFINITION", "Question definition"
        LEGACY_OBSERVATION = "LEGACY_OBSERVATION", "Legacy observation"
        QUESTION_AND_OBSERVATION = (
            "QUESTION_AND_OBSERVATION",
            "Question and legacy observation",
        )
        STRUCTURAL = "STRUCTURAL", "Structural"

    class SourceRole(models.TextChoices):
        TARGET_QUESTIONS = "TARGET_QUESTIONS", "Target questions"
        RANDOM_GENERALIZATION = "RANDOM_GENERALIZATION", "Random generalization"
        KB_RAG = "KB_RAG", "Knowledge base / RAG"
        KNOWN_QUESTIONS = "KNOWN_QUESTIONS", "Known questions"

    class InterpretationSource(models.TextChoices):
        SOURCE_DATA = "SOURCE_DATA", "Source data"
        PRODUCT_OWNER_MAPPING = "PRODUCT_OWNER_MAPPING", "Product-owner mapping"
        STRUCTURAL = "STRUCTURAL", "Structural"

    batch = models.ForeignKey(
        LegacyImportBatch,
        on_delete=models.PROTECT,
        related_name="source_rows",
    )
    sheet_name = models.CharField(max_length=80)
    source_row_number = models.PositiveIntegerField()
    source_role = models.CharField(max_length=32, choices=SourceRole.choices)
    classification = models.CharField(max_length=32, choices=Classification.choices)
    interpretation_source = models.CharField(
        max_length=32,
        choices=InterpretationSource.choices,
        default=InterpretationSource.SOURCE_DATA,
    )
    structural_kind = models.CharField(max_length=40, blank=True)
    source_fingerprint = models.CharField(max_length=64)
    mapping_context = models.JSONField(default=dict)
    domain = models.ForeignKey(
        Domain,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="imported_source_rows",
    )
    question = models.ForeignKey(
        Question,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="imported_source_rows",
    )
    question_version = models.ForeignKey(
        QuestionVersion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="imported_source_rows",
    )

    class Meta:
        ordering = ("sheet_name", "source_row_number")
        constraints = [
            models.UniqueConstraint(
                fields=("batch", "sheet_name", "source_row_number"),
                name="corpus_source_row_unique",
            ),
            models.CheckConstraint(
                condition=Q(
                    classification__in=(
                        "QUESTION_DEFINITION",
                        "LEGACY_OBSERVATION",
                        "QUESTION_AND_OBSERVATION",
                        "STRUCTURAL",
                    )
                ),
                name="corpus_source_row_classification",
            ),
            models.CheckConstraint(
                condition=Q(
                    interpretation_source__in=(
                        "SOURCE_DATA",
                        "PRODUCT_OWNER_MAPPING",
                        "STRUCTURAL",
                    )
                ),
                name="corpus_source_row_interpretation",
            ),
            models.CheckConstraint(
                condition=Q(
                    source_role__in=(
                        "TARGET_QUESTIONS",
                        "RANDOM_GENERALIZATION",
                        "KB_RAG",
                        "KNOWN_QUESTIONS",
                    )
                ),
                name="corpus_source_row_role",
            ),
            models.CheckConstraint(
                condition=(
                    Q(question__isnull=True, question_version__isnull=True)
                    | Q(question__isnull=False, question_version__isnull=False)
                ),
                name="corpus_source_row_question_version_pair",
            ),
            models.CheckConstraint(
                condition=Q(source_row_number__gte=1),
                name="corpus_source_row_number_positive",
            ),
        ]

    def __str__(self):
        return f"{self.sheet_name}!{self.source_row_number}"


class ImportedSourceCell(ImmutableImportRecord):
    source_row = models.ForeignKey(
        ImportedSourceRow,
        on_delete=models.PROTECT,
        related_name="source_cells",
    )
    coordinate = models.CharField(max_length=20)
    column_name = models.CharField(max_length=80, blank=True)
    data_type = models.CharField(max_length=20, blank=True)
    raw_value = models.TextField(null=True, blank=True)
    displayed_value = models.TextField(null=True, blank=True)
    formula = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ("source_row_id", "coordinate")
        constraints = [
            models.UniqueConstraint(
                fields=("source_row", "coordinate"),
                name="corpus_source_cell_unique",
            )
        ]

    def __str__(self):
        return f"{self.source_row}!{self.coordinate}"


class LegacyObservation(ImmutableImportRecord):
    class AnswerFidelity(models.TextChoices):
        SOURCE_TEXT_UNKNOWN_EXACTNESS = (
            "SOURCE_TEXT_UNKNOWN_EXACTNESS",
            "Source text of unknown exactness",
        )

    class ExpectedAnswerRole(models.TextChoices):
        LEGACY_EXPECTATION = "LEGACY_EXPECTATION", "Legacy expectation"

    class JudgmentSource(models.TextChoices):
        IMPORTED_LEGACY = "IMPORTED_LEGACY", "Imported legacy"

    class LegacyJudgment(models.TextChoices):
        GOOD = "GOOD", "Good"
        BAD = "BAD", "Bad"

    source_row = models.OneToOneField(
        ImportedSourceRow,
        on_delete=models.PROTECT,
        related_name="legacy_observation",
    )
    question = models.ForeignKey(
        Question,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="legacy_observations",
    )
    question_version = models.ForeignKey(
        QuestionVersion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="legacy_observations",
    )
    source_question_text = models.TextField()
    observed_answer_text = models.TextField(null=True, blank=True)
    answer_fidelity = models.CharField(max_length=48, choices=AnswerFidelity.choices)
    legacy_expectation = models.TextField(null=True, blank=True)
    expected_answer_role = models.CharField(
        max_length=40,
        choices=ExpectedAnswerRole.choices,
    )
    acceptable_source_value = models.TextField(null=True, blank=True)
    legacy_judgment = models.CharField(
        max_length=8,
        choices=LegacyJudgment.choices,
        null=True,
        blank=True,
    )
    judgment_source = models.CharField(max_length=32, choices=JudgmentSource.choices)
    comments = models.TextField(null=True, blank=True)
    secondary_comments = models.TextField(null=True, blank=True)
    experiment_metadata = models.JSONField(default=dict)
    unknown_metadata = models.JSONField(default=list)
    imported_at = models.DateTimeField()

    class Meta:
        ordering = ("source_row__sheet_name", "source_row__source_row_number")
        constraints = [
            models.CheckConstraint(
                condition=Q(legacy_judgment__isnull=True)
                | Q(legacy_judgment__in=("GOOD", "BAD")),
                name="corpus_legacy_judgment",
            ),
            models.CheckConstraint(
                condition=Q(answer_fidelity="SOURCE_TEXT_UNKNOWN_EXACTNESS"),
                name="corpus_legacy_answer_fidelity",
            ),
            models.CheckConstraint(
                condition=Q(expected_answer_role="LEGACY_EXPECTATION"),
                name="corpus_legacy_expectation_role",
            ),
            models.CheckConstraint(
                condition=Q(judgment_source="IMPORTED_LEGACY"),
                name="corpus_legacy_judgment_source",
            ),
        ]

    def __str__(self):
        return f"Legacy observation {self.source_row}"


class ImportWarning(ImmutableImportRecord):
    class Code(models.TextChoices):
        AMBIGUOUS_CANONICAL_LINK = (
            "AMBIGUOUS_CANONICAL_LINK",
            "Ambiguous canonical link",
        )
        POTENTIAL_BINDING_REQUIRES_REVIEW = (
            "POTENTIAL_BINDING_REQUIRES_REVIEW",
            "Potential binding requires review",
        )
        CONVERSATION_GROUPING_DEFERRED = (
            "CONVERSATION_GROUPING_DEFERRED",
            "Conversation grouping deferred",
        )
        LEGACY_METADATA_UNKNOWN = "LEGACY_METADATA_UNKNOWN", "Legacy metadata unknown"
        UNSUPPORTED_SOURCE_FIELD = "UNSUPPORTED_SOURCE_FIELD", "Unsupported source field"
        SOURCE_CONFLICT = "SOURCE_CONFLICT", "Source conflict"

    batch = models.ForeignKey(
        LegacyImportBatch,
        on_delete=models.PROTECT,
        related_name="warnings",
    )
    sheet_name = models.CharField(max_length=80)
    source_rows = models.JSONField(default=list)
    code = models.CharField(max_length=48, choices=Code.choices)
    explanation = models.TextField()

    class Meta:
        ordering = ("sheet_name", "source_rows", "code", "pk")
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    code__in=(
                        "AMBIGUOUS_CANONICAL_LINK",
                        "POTENTIAL_BINDING_REQUIRES_REVIEW",
                        "CONVERSATION_GROUPING_DEFERRED",
                        "LEGACY_METADATA_UNKNOWN",
                        "UNSUPPORTED_SOURCE_FIELD",
                        "SOURCE_CONFLICT",
                    )
                ),
                name="corpus_import_warning_code",
            )
        ]

    def __str__(self):
        return f"{self.code}: {self.sheet_name} {self.source_rows}"
