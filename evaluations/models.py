import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from catalog.models import EvaluationTarget, Question, QuestionVersion, TargetRevision


class EvaluationRun(models.Model):
    """A durable, one-target M3 run plan.

    The Run can progress while a worker operates, but its selection and target
    identity are captured in related immutable snapshot and Execution rows.
    """

    class State(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS", "Completed with errors"
        FAILED = "FAILED", "Failed"

    class ExecutionMode(models.TextChoices):
        SEQUENTIAL = "SEQUENTIAL", "Sequential"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    target = models.ForeignKey(EvaluationTarget, on_delete=models.PROTECT, related_name="runs")
    target_revision = models.ForeignKey(
        TargetRevision,
        on_delete=models.PROTECT,
        related_name="runs",
    )
    launched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="launched_evaluation_runs",
    )
    state = models.CharField(max_length=24, choices=State.choices, default=State.PENDING)
    requested_mode = models.CharField(
        max_length=12,
        choices=ExecutionMode.choices,
        default=ExecutionMode.SEQUENTIAL,
    )
    configured_max_concurrency = models.PositiveSmallIntegerField(default=1)
    actual_concurrency = models.PositiveSmallIntegerField(default=1)
    question_timeout_seconds = models.PositiveIntegerField()
    inter_question_delay_seconds = models.DecimalField(max_digits=7, decimal_places=3, default=0)
    total_planned = models.PositiveIntegerField()
    selection_filter = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    diagnostic_class = models.CharField(max_length=80, blank=True)
    diagnostic_detail = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    state__in=(
                        "PENDING",
                        "RUNNING",
                        "COMPLETED",
                        "COMPLETED_WITH_ERRORS",
                        "FAILED",
                    )
                ),
                name="evaluations_run_state",
            ),
            models.CheckConstraint(
                condition=Q(requested_mode="SEQUENTIAL"),
                name="evaluations_m3_sequential_only",
            ),
            models.CheckConstraint(
                condition=Q(actual_concurrency=1),
                name="evaluations_m3_actual_concurrency_one",
            ),
            models.CheckConstraint(
                condition=Q(total_planned__gte=1),
                name="evaluations_run_nonempty_manifest",
            ),
        ]

    def __str__(self):
        return str(self.id)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values("state").first()
            if previous and previous["state"] in {
                self.State.COMPLETED,
                self.State.COMPLETED_WITH_ERRORS,
                self.State.FAILED,
            }:
                raise ValidationError("Completed evaluation runs are immutable.")
        return super().save(*args, **kwargs)

    @property
    def is_terminal(self):
        return self.state in {
            self.State.COMPLETED,
            self.State.COMPLETED_WITH_ERRORS,
            self.State.FAILED,
        }


class TargetSnapshot(models.Model):
    """Immutable execution-safe copy of the configured target revision."""

    run = models.OneToOneField(EvaluationRun, on_delete=models.PROTECT, related_name="target_snapshot")
    target = models.ForeignKey(EvaluationTarget, on_delete=models.PROTECT, related_name="target_snapshots")
    target_revision = models.ForeignKey(
        TargetRevision,
        on_delete=models.PROTECT,
        related_name="target_snapshots",
    )
    target_display_name = models.CharField(max_length=180)
    product_display_name = models.CharField(max_length=160)
    environment_display_name = models.CharField(max_length=160)
    endpoint = models.URLField(max_length=500)
    adapter_key = models.CharField(max_length=100)
    adapter_version = models.CharField(max_length=80)
    credential_reference = models.CharField(max_length=128, blank=True)
    classification = models.CharField(max_length=16)
    supports_runtime_metadata = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Target snapshots are immutable.")
        return super().save(*args, **kwargs)


class BuildSnapshot(models.Model):
    """Declared launch identity plus one non-fatal runtime observation for a run."""

    class RuntimeState(models.TextChoices):
        NOT_ATTEMPTED = "NOT_ATTEMPTED", "Not attempted"
        AVAILABLE = "AVAILABLE", "Available"
        UNAVAILABLE = "UNAVAILABLE", "Unavailable"
        MALFORMED = "MALFORMED", "Malformed"

    run = models.OneToOneField(EvaluationRun, on_delete=models.PROTECT, related_name="build_snapshot")
    declared_product_version = models.CharField(max_length=120, blank=True)
    declared_build_id = models.CharField(max_length=160, blank=True)
    declared_git_sha = models.CharField(max_length=64, blank=True)
    runtime_state = models.CharField(
        max_length=16,
        choices=RuntimeState.choices,
        default=RuntimeState.NOT_ATTEMPTED,
    )
    runtime_metadata = models.JSONField(default=dict, blank=True)
    runtime_raw_response = models.TextField(blank=True)
    runtime_observed_at = models.DateTimeField(null=True, blank=True)
    runtime_diagnostic = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(runtime_state__in=("NOT_ATTEMPTED", "AVAILABLE", "UNAVAILABLE", "MALFORMED")),
                name="evaluations_build_snapshot_runtime_state",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding and EvaluationRun.objects.filter(
            pk=self.run_id,
            state__in=(
                EvaluationRun.State.COMPLETED,
                EvaluationRun.State.COMPLETED_WITH_ERRORS,
                EvaluationRun.State.FAILED,
            ),
        ).exists():
            raise ValidationError("Build snapshots for completed runs are immutable.")
        return super().save(*args, **kwargs)


class Execution(models.Model):
    class Outcome(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        SUCCESS = "SUCCESS", "Success"
        ERROR = "ERROR", "Error"
        TIMEOUT = "TIMEOUT", "Timeout"

    run = models.ForeignKey(EvaluationRun, on_delete=models.PROTECT, related_name="executions")
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="executions")
    question_version = models.ForeignKey(
        QuestionVersion,
        on_delete=models.PROTECT,
        related_name="executions",
    )
    target_revision = models.ForeignKey(TargetRevision, on_delete=models.PROTECT)
    target_snapshot = models.ForeignKey(TargetSnapshot, on_delete=models.PROTECT)
    build_snapshot = models.ForeignKey(BuildSnapshot, on_delete=models.PROTECT)
    question_order = models.PositiveIntegerField()
    question_stable_id = models.CharField(max_length=120)
    question_version_number = models.PositiveIntegerField()
    question_template = models.TextField()
    submitted_question = models.TextField()
    outcome = models.CharField(max_length=12, choices=Outcome.choices, default=Outcome.PENDING)
    request_correlation_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    adapter_key = models.CharField(max_length=100)
    adapter_version = models.CharField(max_length=80)
    normalizer_key = models.CharField(max_length=80, default="identity-display")
    normalizer_version = models.CharField(max_length=32, default="1")
    raw_request = models.JSONField(default=dict, blank=True)
    protocol_status = models.PositiveSmallIntegerField(null=True, blank=True)
    raw_response = models.TextField(blank=True)
    raw_answer = models.TextField(blank=True)
    display_answer = models.TextField(blank=True)
    evidence = models.JSONField(default=dict, blank=True)
    response_metadata = models.JSONField(default=dict, blank=True)
    target_correlation_id = models.CharField(max_length=160, blank=True)
    error_class = models.CharField(max_length=80, blank=True)
    error_detail = models.TextField(blank=True)
    preflight_error_class = models.CharField(max_length=80, blank=True)
    preflight_error_detail = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ("run", "question_order")
        constraints = [
            models.UniqueConstraint(
                fields=("run", "question_order"),
                name="evaluations_manifest_order_unique",
            ),
            models.CheckConstraint(
                condition=Q(outcome__in=("PENDING", "RUNNING", "SUCCESS", "ERROR", "TIMEOUT")),
                name="evaluations_execution_outcome",
            ),
        ]

    def __str__(self):
        return f"{self.run_id} #{self.question_order} {self.question_stable_id}"

    @property
    def is_terminal(self):
        return self.outcome in {self.Outcome.SUCCESS, self.Outcome.ERROR, self.Outcome.TIMEOUT}

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values("outcome").first()
            if previous and previous["outcome"] in {
                self.Outcome.SUCCESS,
                self.Outcome.ERROR,
                self.Outcome.TIMEOUT,
            }:
                raise ValidationError("Terminal execution observations are immutable.")
        return super().save(*args, **kwargs)


class ResolvedBinding(models.Model):
    class ResolutionMode(models.TextChoices):
        FIXED_ADMIN = "FIXED_ADMIN", "Fixed admin"

    execution = models.ForeignKey(Execution, on_delete=models.PROTECT, related_name="resolved_bindings")
    name = models.CharField(max_length=80)
    resolution_mode = models.CharField(max_length=24, choices=ResolutionMode.choices)
    value = models.JSONField()
    display_value = models.TextField()

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("execution", "name"),
                name="evaluations_resolved_binding_name_unique",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Resolved bindings are immutable.")
        return super().save(*args, **kwargs)
