from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q


stable_id_validator = RegexValidator(
    regex=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    message="Use letters, numbers, dots, underscores, and hyphens only.",
)
credential_reference_validator = RegexValidator(
    regex=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$",
    message="Use a symbolic external reference, not credential material.",
)


class AttributedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_%(app_label)s_%(class)s_records",
    )

    class Meta:
        abstract = True


class Product(AttributedModel):
    slug = models.SlugField(max_length=80, unique=True)
    display_name = models.CharField(max_length=160, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_catalog_products",
    )

    class Meta:
        ordering = ("display_name",)

    def __str__(self):
        return self.display_name


class Environment(AttributedModel):
    slug = models.SlugField(max_length=80, unique=True)
    display_name = models.CharField(max_length=160, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_catalog_environments",
    )

    class Meta:
        ordering = ("display_name",)

    def __str__(self):
        return self.display_name


class Domain(AttributedModel):
    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_catalog_domains",
    )

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Tag(AttributedModel):
    name = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class EvaluationTarget(AttributedModel):
    slug = models.SlugField(max_length=100, unique=True)
    display_name = models.CharField(max_length=180, unique=True)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="targets")
    environment = models.ForeignKey(
        Environment,
        on_delete=models.PROTECT,
        related_name="targets",
    )
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_catalog_targets",
    )

    class Meta:
        ordering = ("display_name",)

    def __str__(self):
        return self.display_name

    @property
    def current_revision(self):
        return self.revisions.filter(valid_to__isnull=True).first()


class ImmutableTemporalModel(AttributedModel):
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "Historical records are immutable; create a new revision or version."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Historical records cannot be deleted.")


class TargetRevision(ImmutableTemporalModel):
    class Classification(models.TextChoices):
        PRODUCTION = "PRODUCTION", "Production"
        DEVELOPMENT = "DEVELOPMENT", "Development"
        STAGING = "STAGING", "Staging"
        LAB_TEST = "LAB_TEST", "Lab/test"
        EXTERNAL = "EXTERNAL", "External"

    class ExecutionMode(models.TextChoices):
        SEQUENTIAL = "SEQUENTIAL", "Sequential"
        PARALLEL = "PARALLEL", "Parallel"

    target = models.ForeignKey(
        EvaluationTarget,
        on_delete=models.PROTECT,
        related_name="revisions",
    )
    revision_number = models.PositiveIntegerField()
    endpoint = models.URLField(max_length=500)
    adapter_key = models.CharField(max_length=100)
    adapter_version = models.CharField(max_length=80)
    credential_reference = models.CharField(
        max_length=128,
        blank=True,
        validators=[credential_reference_validator],
        help_text="Symbolic deployment-secret reference only; never enter a credential value.",
    )
    classification = models.CharField(max_length=16, choices=Classification.choices)
    supports_question_api = models.BooleanField(default=True)
    supports_conversation_session = models.BooleanField(default=False)
    supports_runtime_metadata = models.BooleanField(default=False)
    supports_health_check = models.BooleanField(default=False)
    default_execution_mode = models.CharField(
        max_length=12,
        choices=ExecutionMode.choices,
        default=ExecutionMode.SEQUENTIAL,
    )
    max_concurrency = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(64)],
    )
    question_timeout_seconds = models.PositiveIntegerField(
        default=120,
        validators=[MinValueValidator(1), MaxValueValidator(86400)],
    )
    inter_question_delay_seconds = models.DecimalField(
        max_digits=7,
        decimal_places=3,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(3600)],
    )
    declared_product_version = models.CharField(max_length=120, blank=True)
    declared_build_id = models.CharField(max_length=160, blank=True)
    declared_git_sha = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ("-revision_number",)
        constraints = [
            models.UniqueConstraint(
                fields=("target", "revision_number"),
                name="catalog_target_revision_number_unique",
            ),
            models.UniqueConstraint(
                fields=("target",),
                condition=Q(valid_to__isnull=True),
                name="catalog_target_one_current_revision",
            ),
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gt=models.F("valid_from")),
                name="catalog_target_revision_valid_range",
            ),
            models.CheckConstraint(
                condition=Q(
                    classification__in=(
                        "PRODUCTION",
                        "DEVELOPMENT",
                        "STAGING",
                        "LAB_TEST",
                        "EXTERNAL",
                    )
                ),
                name="catalog_target_revision_classification",
            ),
            models.CheckConstraint(
                condition=Q(default_execution_mode__in=("SEQUENTIAL", "PARALLEL")),
                name="catalog_target_revision_mode",
            ),
            models.CheckConstraint(
                condition=Q(max_concurrency__gte=1) & Q(max_concurrency__lte=64),
                name="catalog_target_revision_concurrency",
            ),
            models.CheckConstraint(
                condition=Q(question_timeout_seconds__gte=1)
                & Q(question_timeout_seconds__lte=86400),
                name="catalog_target_revision_timeout",
            ),
            models.CheckConstraint(
                condition=Q(inter_question_delay_seconds__gte=0)
                & Q(inter_question_delay_seconds__lte=3600),
                name="catalog_target_revision_delay",
            ),
        ]

    def __str__(self):
        return f"{self.target} r{self.revision_number}"

    def clean(self):
        super().clean()
        parsed = urlsplit(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValidationError({"endpoint": "Enter an HTTP or HTTPS base endpoint."})
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValidationError(
                {"endpoint": "Endpoint must not contain credentials, query parameters, or fragments."}
            )


class Question(AttributedModel):
    class Kind(models.TextChoices):
        SINGLE_TURN = "SINGLE_TURN", "Single turn"
        CONVERSATION = "CONVERSATION", "Conversation"

    class Lifecycle(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        RETIRED = "RETIRED", "Retired"

    stable_id = models.CharField(max_length=120, unique=True, validators=[stable_id_validator])
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SINGLE_TURN)
    lifecycle = models.CharField(
        max_length=8,
        choices=Lifecycle.choices,
        default=Lifecycle.DRAFT,
    )
    domain = models.ForeignKey(
        Domain,
        on_delete=models.PROTECT,
        related_name="questions",
        null=True,
        blank=True,
    )
    tags = models.ManyToManyField(Tag, related_name="questions", blank=True)
    rationale = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_catalog_questions",
    )

    class Meta:
        ordering = ("stable_id",)
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=("SINGLE_TURN", "CONVERSATION")),
                name="catalog_question_kind",
            ),
            models.CheckConstraint(
                condition=Q(lifecycle__in=("DRAFT", "ACTIVE", "RETIRED")),
                name="catalog_question_lifecycle",
            ),
            models.CheckConstraint(
                condition=~Q(lifecycle="ACTIVE") | Q(domain__isnull=False),
                name="catalog_active_question_has_domain",
            ),
        ]

    def __str__(self):
        return self.stable_id

    @property
    def current_version(self):
        return self.versions.filter(valid_to__isnull=True).first()


class QuestionVersion(ImmutableTemporalModel):
    class ChangeType(models.TextChoices):
        PRODUCT_REQUIREMENT_CHANGE = (
            "PRODUCT_REQUIREMENT_CHANGE",
            "Product requirement change",
        )
        TEST_BUG_FIX = "TEST_BUG_FIX", "Test bug fix"
        GROUND_TRUTH_UPDATE = "GROUND_TRUTH_UPDATE", "Ground truth update"
        DATA_MODEL_EVOLUTION = "DATA_MODEL_EVOLUTION", "Data model evolution"

    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="versions")
    version_number = models.PositiveIntegerField()
    question_text = models.TextField()
    evaluation_guidance = models.TextField(blank=True)
    change_type = models.CharField(max_length=32, choices=ChangeType.choices, blank=True)
    change_reason = models.TextField(blank=True)

    class Meta:
        ordering = ("-version_number",)
        constraints = [
            models.UniqueConstraint(
                fields=("question", "version_number"),
                name="catalog_question_version_number_unique",
            ),
            models.UniqueConstraint(
                fields=("question",),
                condition=Q(valid_to__isnull=True),
                name="catalog_question_one_current_version",
            ),
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gt=models.F("valid_from")),
                name="catalog_question_version_valid_range",
            ),
            models.CheckConstraint(
                condition=Q(change_type="")
                | Q(
                    change_type__in=(
                        "PRODUCT_REQUIREMENT_CHANGE",
                        "TEST_BUG_FIX",
                        "GROUND_TRUTH_UPDATE",
                        "DATA_MODEL_EVOLUTION",
                    )
                ),
                name="catalog_question_version_change_type",
            ),
        ]

    def __str__(self):
        return f"{self.question.stable_id} v{self.version_number}"


class BindingDefinition(AttributedModel):
    class ValueType(models.TextChoices):
        TEXT = "TEXT", "Text"
        IDENTIFIER = "IDENTIFIER", "Identifier"
        INTEGER = "INTEGER", "Integer"
        DECIMAL = "DECIMAL", "Decimal"
        TIMESTAMP = "TIMESTAMP", "Timestamp"

    question_version = models.ForeignKey(
        QuestionVersion,
        on_delete=models.PROTECT,
        related_name="binding_definitions",
    )
    name = models.CharField(max_length=80, validators=[stable_id_validator])
    value_type = models.CharField(max_length=16, choices=ValueType.choices)
    is_required = models.BooleanField(default=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("question_version", "name"),
                name="catalog_binding_name_per_version_unique",
            ),
            models.CheckConstraint(
                condition=Q(
                    value_type__in=("TEXT", "IDENTIFIER", "INTEGER", "DECIMAL", "TIMESTAMP")
                ),
                name="catalog_binding_value_type",
            ),
        ]

    def __str__(self):
        return f"{self.question_version}: {self.name}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Binding definitions are immutable with their question version.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Binding definitions cannot be deleted.")


class HistoricalFixture(AttributedModel):
    stable_id = models.CharField(max_length=120, unique=True, validators=[stable_id_validator])
    name = models.CharField(max_length=180)
    environment = models.ForeignKey(
        Environment,
        on_delete=models.PROTECT,
        related_name="historical_fixtures",
    )
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    description = models.TextField(blank=True)
    tags = models.ManyToManyField(Tag, related_name="historical_fixtures", blank=True)
    fixed_parameters = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-window_start", "stable_id")
        constraints = [
            models.CheckConstraint(
                condition=Q(window_end__gt=models.F("window_start")),
                name="catalog_fixture_valid_window",
            )
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.window_start and self.window_end and self.window_end <= self.window_start:
            raise ValidationError({"window_end": "Window end must be after window start."})
        if not isinstance(self.fixed_parameters, dict):
            raise ValidationError({"fixed_parameters": "Fixed parameters must be an object."})
        sensitive_fragments = ("password", "secret", "token", "authorization", "cookie")

        def contains_sensitive_key(value):
            if isinstance(value, dict):
                return any(
                    any(fragment in str(key).casefold() for fragment in sensitive_fragments)
                    or contains_sensitive_key(child)
                    for key, child in value.items()
                )
            if isinstance(value, list):
                return any(contains_sensitive_key(child) for child in value)
            return False

        if contains_sensitive_key(self.fixed_parameters):
            raise ValidationError(
                {"fixed_parameters": "Fixed parameters cannot contain credential material."}
            )
