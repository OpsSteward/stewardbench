import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from catalog.models import (
    ConversationScenarioVersion,
    ConversationTurn,
    EvaluationTarget,
    Question,
    QuestionVersion,
    TargetRevision,
)


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
        PARALLEL = "PARALLEL", "Parallel"

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
    next_dispatch_at = models.DateTimeField(null=True, blank=True)
    diagnostic_class = models.CharField(max_length=80, blank=True)
    diagnostic_detail = models.TextField(blank=True)
    source_run = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="rerun_runs",
    )
    source_execution = models.ForeignKey(
        "Execution",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="retry_runs",
    )
    retry_request_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    comparison_baseline = models.ForeignKey(
        "Baseline",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="controlled_runs",
    )

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
                condition=Q(requested_mode__in=("SEQUENTIAL", "PARALLEL")),
                name="evaluations_run_execution_mode",
            ),
            models.CheckConstraint(
                condition=Q(configured_max_concurrency__gte=1)
                & Q(actual_concurrency__gte=1)
                & Q(actual_concurrency__lte=models.F("configured_max_concurrency")),
                name="evaluations_run_concurrency_bounds",
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


class ConversationAttempt(models.Model):
    """Durable ownership of one target conversation session for a full scenario run."""

    class SessionState(models.TextChoices):
        PENDING = "PENDING", "Pending session"
        ACTIVE = "ACTIVE", "Active"
        UNUSABLE = "UNUSABLE", "Session unusable"
        CLOSED = "CLOSED", "Closed"

    run = models.OneToOneField(EvaluationRun, on_delete=models.PROTECT, related_name="conversation_attempt")
    scenario_version = models.ForeignKey(
        ConversationScenarioVersion,
        on_delete=models.PROTECT,
        related_name="attempts",
    )
    source_attempt = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="retry_attempts",
    )
    baseline_attempt = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="controlled_replay_attempts",
    )
    target_session_id = models.CharField(max_length=200, blank=True)
    session_metadata = models.JSONField(default=dict, blank=True)
    session_state = models.CharField(max_length=12, choices=SessionState.choices, default=SessionState.PENDING)
    session_diagnostic = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-run__created_at",)
        constraints = [
            models.CheckConstraint(
                condition=Q(session_state__in=("PENDING", "ACTIVE", "UNUSABLE", "CLOSED")),
                name="evaluations_conversation_session_state",
            ),
        ]

    def __str__(self):
        return f"{self.scenario_version} attempt {self.pk}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values("target_session_id").first()
            if previous and previous["target_session_id"] and previous["target_session_id"] != self.target_session_id:
                raise ValidationError("A historical target session identity cannot be replaced.")
        return super().save(*args, **kwargs)

    @property
    def overall_human_result(self):
        """Derived result; it is intentionally not a separate editable judgment."""

        required = self.turn_executions.filter(conversation_turn__required_for_overall=True)
        # Human BAD is authoritative whenever present.  A transport failure is
        # still visible on its turn and prevents GOOD, but must not erase an
        # already recorded required-turn BAD from the derived human result.
        if required.filter(current_human_review__judgment=HumanReview.Judgment.BAD).exists():
            return "BAD"
        if required.filter(outcome__in=(Execution.Outcome.PENDING, Execution.Outcome.RUNNING, Execution.Outcome.ERROR, Execution.Outcome.TIMEOUT)).exists():
            return "EXECUTION_INCOMPLETE"
        if required.exists() and required.filter(current_human_review__judgment=HumanReview.Judgment.GOOD).count() == required.count():
            return "GOOD"
        return "NOT_FULLY_REVIEWED"


class Execution(models.Model):
    class Outcome(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        SUCCESS = "SUCCESS", "Success"
        ERROR = "ERROR", "Error"
        TIMEOUT = "TIMEOUT", "Timeout"

    class TargetCallPhase(models.TextChoices):
        """The recovery-relevant boundary of the target question call.

        ``LEGACY_UNKNOWN`` is reserved for a non-terminal M3 row encountered
        by the forward-only M4 migration.  It is never assigned to new work
        and is conservatively finalized during reconciliation.
        """

        NONE = "NONE", "No active claim"
        CLAIMED = "CLAIMED", "Claimed before target submission"
        SUBMISSION_STARTED = "SUBMISSION_STARTED", "Target submission may have occurred"
        TERMINAL = "TERMINAL", "Terminal observation persisted"
        LEGACY_UNKNOWN = "LEGACY_UNKNOWN", "Legacy interrupted work"

    class ReviewState(models.TextChoices):
        NONE = "NONE", "None"
        REQUIRED = "REQUIRED", "Required"
        REVIEWED = "REVIEWED", "Reviewed"

    class Validity(models.TextChoices):
        VALID = "VALID", "Valid"
        INVALID = "INVALID", "Invalid"

    run = models.ForeignKey(EvaluationRun, on_delete=models.PROTECT, related_name="executions")
    question = models.ForeignKey(
        Question,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="executions",
    )
    question_version = models.ForeignKey(
        QuestionVersion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="executions",
    )
    conversation_attempt = models.ForeignKey(
        ConversationAttempt,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="turn_executions",
    )
    conversation_turn = models.ForeignKey(
        ConversationTurn,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="executions",
    )
    target_revision = models.ForeignKey(TargetRevision, on_delete=models.PROTECT)
    target_snapshot = models.ForeignKey(TargetSnapshot, on_delete=models.PROTECT)
    build_snapshot = models.ForeignKey(BuildSnapshot, on_delete=models.PROTECT)
    question_order = models.PositiveIntegerField()
    question_stable_id = models.CharField(max_length=120)
    question_version_number = models.PositiveIntegerField(default=0)
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
    comparison_non_comparable_reason = models.CharField(max_length=120, blank=True)
    claim_worker_id = models.CharField(max_length=200, blank=True)
    claim_token = models.UUIDField(null=True, blank=True, editable=False)
    claim_attempt = models.PositiveIntegerField(default=0)
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_lease_expires_at = models.DateTimeField(null=True, blank=True)
    claim_heartbeat_at = models.DateTimeField(null=True, blank=True)
    target_call_phase = models.CharField(
        max_length=24,
        choices=TargetCallPhase.choices,
        default=TargetCallPhase.NONE,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    # External request timing and target-reported telemetry are deliberately
    # separate immutable Execution evidence.
    performance_policy_version = models.CharField(max_length=80, default="opss-performance-v1")
    performance_classification = models.CharField(max_length=16, blank=True)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    total_tokens = models.PositiveIntegerField(null=True, blank=True)
    token_usage_metadata = models.JSONField(default=dict, blank=True)
    runtime_telemetry = models.JSONField(default=dict, blank=True)
    internal_timing_metadata = models.JSONField(default=dict, blank=True)
    review_state = models.CharField(
        max_length=12,
        choices=ReviewState.choices,
        default=ReviewState.NONE,
    )
    current_human_review = models.ForeignKey(
        "HumanReview",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_for_executions",
    )
    validity = models.CharField(
        max_length=8,
        choices=Validity.choices,
        default=Validity.VALID,
    )
    invalidated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="invalidated_executions",
    )
    invalidated_at = models.DateTimeField(null=True, blank=True)
    source_execution = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="retried_executions",
    )
    baseline_execution = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="controlled_replay_executions",
        help_text="Historical baseline observation whose exact inputs this controlled replay uses.",
    )

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
            models.CheckConstraint(
                condition=(
                    Q(
                        conversation_attempt__isnull=True,
                        conversation_turn__isnull=True,
                        question__isnull=False,
                        question_version__isnull=False,
                    )
                    | Q(
                        conversation_attempt__isnull=False,
                        conversation_turn__isnull=False,
                    )
                ),
                name="evaluations_execution_question_or_conversation_turn",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        outcome="PENDING",
                        target_call_phase="NONE",
                        claim_worker_id="",
                        claim_token__isnull=True,
                        claimed_at__isnull=True,
                        claim_lease_expires_at__isnull=True,
                        claim_heartbeat_at__isnull=True,
                    )
                    |
                    Q(
                        outcome="RUNNING",
                        target_call_phase__in=("CLAIMED", "SUBMISSION_STARTED"),
                        claim_token__isnull=False,
                        claimed_at__isnull=False,
                        claim_lease_expires_at__isnull=False,
                        claim_heartbeat_at__isnull=False,
                    )
                    & ~Q(claim_worker_id="")
                    |
                    Q(
                        outcome="RUNNING",
                        target_call_phase__in=("NONE", "LEGACY_UNKNOWN"),
                        claim_worker_id="",
                        claim_token__isnull=True,
                    )
                    | Q(
                        outcome__in=("SUCCESS", "ERROR", "TIMEOUT"),
                        target_call_phase__in=("NONE", "TERMINAL"),
                    )
                ),
                name="evaluations_execution_claim_state",
            ),
            models.CheckConstraint(
                condition=Q(review_state__in=("NONE", "REQUIRED", "REVIEWED")),
                name="evaluations_execution_review_state",
            ),
            models.CheckConstraint(
                condition=Q(validity__in=("VALID", "INVALID")),
                name="evaluations_execution_validity",
            ),
        ]
        indexes = [
            models.Index(
                fields=("outcome", "target_revision", "claim_lease_expires_at"),
                name="eval_exec_claim_idx",
            ),
            models.Index(
                fields=("run", "outcome", "question_order"),
                name="eval_exec_run_claim_idx",
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
        BASELINE_FROZEN = "BASELINE_FROZEN", "Baseline frozen"

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


class Comment(models.Model):
    """Append-only operational context for exactly one Run or Execution."""

    run = models.ForeignKey(
        EvaluationRun,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="comments",
    )
    execution = models.ForeignKey(
        Execution,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="stewardbench_comments",
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(run__isnull=False, execution__isnull=True)
                    | Q(run__isnull=True, execution__isnull=False)
                ),
                name="evaluations_comment_one_parent",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Comments are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Comments are append-only and cannot be deleted.")


class HumanReview(models.Model):
    """One immutable judgment event; the Execution points to the current event."""

    class Judgment(models.TextChoices):
        GOOD = "GOOD", "Good"
        BAD = "BAD", "Bad"

    execution = models.ForeignKey(
        Execution,
        on_delete=models.PROTECT,
        related_name="review_history",
    )
    judgment = models.CharField(max_length=4, choices=Judgment.choices)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="human_reviews",
    )
    reviewed_at = models.DateTimeField(auto_now_add=True)
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="corrections",
    )
    comment = models.ForeignKey(
        Comment,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="review_events",
    )

    class Meta:
        ordering = ("reviewed_at", "id")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Human reviews are immutable; append a correction review instead.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Human reviews are append-only and cannot be deleted.")


class ReviewTracking(models.Model):
    """Attributed state-history for the independent review-workflow projection."""

    execution = models.ForeignKey(
        Execution,
        on_delete=models.PROTECT,
        related_name="review_tracking_events",
    )
    state = models.CharField(max_length=12, choices=Execution.ReviewState.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="review_tracking_events",
    )
    cause = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Review tracking is append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Review tracking is append-only and cannot be deleted.")


class ExecutionValidityDecision(models.Model):
    """Append-only attributed validity decision with a current Execution projection."""

    execution = models.ForeignKey(
        Execution,
        on_delete=models.PROTECT,
        related_name="validity_history",
    )
    validity = models.CharField(max_length=8, choices=Execution.Validity.choices)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="execution_validity_decisions",
    )
    decided_at = models.DateTimeField(auto_now_add=True)
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="corrections",
    )
    comment = models.ForeignKey(
        Comment,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="validity_decisions",
    )

    class Meta:
        ordering = ("decided_at", "id")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Validity decisions are immutable; append a correction decision instead.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Validity decisions are append-only and cannot be deleted.")


class AutomatedEvaluationResult(models.Model):
    """Immutable M9 deterministic/policy evaluator evidence.

    The append-only ``supersedes`` chain describes a newer requested
    evaluation for the same evaluator identity.  Result data never mutates an
    Execution observation or its review/comparison projections.
    """

    class Status(models.TextChoices):
        COMPLETE = "COMPLETE", "Complete"
        NOT_APPLICABLE = "NOT_APPLICABLE", "Not applicable"
        ERROR = "ERROR", "Error"

    class Mechanism(models.TextChoices):
        DETERMINISTIC = "DETERMINISTIC", "Deterministic"
        POLICY = "POLICY", "Policy"
        EXPECTED_CANNOT_CONCLUDE = "EXPECTED_CANNOT_CONCLUDE", "Expected cannot conclude"

    class Outcome(models.TextChoices):
        PASS = "PASS", "Pass"
        FAIL = "FAIL", "Fail"
        CANNOT_CONCLUDE = "CANNOT_CONCLUDE", "Cannot conclude"

    execution = models.ForeignKey(
        Execution,
        on_delete=models.PROTECT,
        related_name="automated_results",
    )
    evaluator_key = models.CharField(max_length=100)
    evaluator_version = models.CharField(max_length=80)
    mechanism = models.CharField(max_length=32, choices=Mechanism.choices, default=Mechanism.DETERMINISTIC)
    configuration_version = models.CharField(max_length=80, default="legacy-m5")
    status = models.CharField(max_length=16, choices=Status.choices)
    outcome = models.CharField(max_length=20, choices=Outcome.choices, blank=True)
    details = models.JSONField(default=dict, blank=True)
    input_fingerprint = models.CharField(max_length=64, blank=True)
    input_manifest = models.JSONField(default=dict, blank=True)
    raw_result = models.JSONField(default=dict, blank=True)
    error_class = models.CharField(max_length=100, blank=True)
    error_detail = models.TextField(blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    invocation = models.ForeignKey(
        "EvaluationInvocation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="automated_results",
    )
    supersedes = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Automated evaluation results are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Automated evaluation results are immutable and cannot be deleted.")


class LLMJudgeResult(models.Model):
    """Immutable M9 advisory judge evidence for one stored Execution."""

    class Status(models.TextChoices):
        COMPLETE = "COMPLETE", "Complete"
        ERROR = "ERROR", "Error"

    execution = models.ForeignKey(
        Execution,
        on_delete=models.PROTECT,
        related_name="llm_judge_results",
    )
    provider = models.CharField(max_length=100)
    model_identifier = models.CharField(max_length=160)
    judge_version = models.CharField(max_length=80)
    rubric_id = models.CharField(max_length=100, default="legacy-unknown")
    rubric_version = models.CharField(max_length=80, default="legacy-m5")
    prompt_version = models.CharField(max_length=80)
    status = models.CharField(max_length=12, choices=Status.choices)
    dimensions = models.JSONField(default=dict, blank=True)
    rationale = models.TextField(blank=True)
    advisory_disposition = models.CharField(max_length=80, blank=True)
    details = models.JSONField(default=dict, blank=True)
    input_fingerprint = models.CharField(max_length=64, blank=True)
    input_manifest = models.JSONField(default=dict, blank=True)
    raw_result = models.JSONField(default=dict, blank=True)
    provider_metadata = models.JSONField(default=dict, blank=True)
    error_class = models.CharField(max_length=100, blank=True)
    error_detail = models.TextField(blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    invocation = models.ForeignKey(
        "EvaluationInvocation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="judge_results",
    )
    supersedes = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("LLM judge results are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("LLM judge results are immutable and cannot be deleted.")


class EvaluationInvocation(models.Model):
    """Durable M9 work item for analysis of an already stored observation.

    This is intentionally independent from the product ``Execution`` work
    lifecycle.  It holds no target request, credentials, answer copy, or target
    concurrency state.  The worker may safely process it after a browser POST
    has returned.
    """

    class Kind(models.TextChoices):
        EVALUATOR = "EVALUATOR", "Evaluator"
        JUDGE = "JUDGE", "LLM judge"

    class State(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    execution = models.ForeignKey(Execution, on_delete=models.PROTECT, related_name="evaluation_invocations")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    state = models.CharField(max_length=12, choices=State.choices, default=State.PENDING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_evaluation_invocations",
    )
    evaluator_key = models.CharField(max_length=100)
    evaluator_version = models.CharField(max_length=80)
    mechanism = models.CharField(max_length=32, blank=True)
    provider = models.CharField(max_length=100, blank=True)
    model_identifier = models.CharField(max_length=160, blank=True)
    judge_version = models.CharField(max_length=80, blank=True)
    rubric_id = models.CharField(max_length=100, blank=True)
    rubric_version = models.CharField(max_length=80, blank=True)
    prompt_version = models.CharField(max_length=80, blank=True)
    configuration = models.JSONField(default=dict, blank=True)
    input_fingerprint = models.CharField(max_length=64, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    worker_id = models.CharField(max_length=200, blank=True)
    claim_token = models.UUIDField(null=True, blank=True, editable=False)
    claim_attempt = models.PositiveIntegerField(default=0)
    claim_heartbeat_at = models.DateTimeField(null=True, blank=True)
    claim_lease_expires_at = models.DateTimeField(null=True, blank=True)
    result_error_class = models.CharField(max_length=100, blank=True)
    result_error_detail = models.TextField(blank=True)

    class Meta:
        ordering = ("id",)
        indexes = [
            models.Index(fields=("state", "kind", "id"), name="eval_invocation_claim_idx"),
            models.Index(fields=("execution", "kind", "id"), name="eval_invocation_current_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=("EVALUATOR", "JUDGE")),
                name="evaluations_invocation_kind",
            ),
            models.CheckConstraint(
                condition=Q(state__in=("PENDING", "RUNNING", "COMPLETED", "FAILED")),
                name="evaluations_invocation_state",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        state="PENDING",
                        worker_id="",
                        claim_token__isnull=True,
                        claim_heartbeat_at__isnull=True,
                        claim_lease_expires_at__isnull=True,
                    )
                    | Q(
                        state="RUNNING",
                        claim_token__isnull=False,
                        claim_heartbeat_at__isnull=False,
                        claim_lease_expires_at__isnull=False,
                    )
                    & ~Q(worker_id="")
                    | Q(state__in=("COMPLETED", "FAILED"))
                ),
                name="evaluations_invocation_claim_state",
            ),
        ]


class Baseline(models.Model):
    """A named immutable reference to observations from one completed Run.

    The administrative active and attention projections intentionally sit beside
    the immutable source/membership fields.  Their attributed histories live in
    separate append-only event rows below.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    source_run = models.ForeignKey(
        EvaluationRun,
        on_delete=models.PROTECT,
        related_name="promoted_baselines",
    )
    source_target = models.ForeignKey(
        EvaluationTarget,
        on_delete=models.PROTECT,
        related_name="baselines",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_baselines",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    requires_attention = models.BooleanField(default=False)
    attention_opened_at = models.DateTimeField(null=True, blank=True)
    attention_detail = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("source_target", "name"),
                name="evaluations_baseline_name_per_target_unique",
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "Baselines are immutable; use the attributed service to change active state."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Baselines are retained historical references and cannot be deleted.")


class BaselineMembership(models.Model):
    """Immutable captured Baseline membership; it never absorbs retries."""

    baseline = models.ForeignKey(
        Baseline,
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    execution = models.ForeignKey(
        Execution,
        on_delete=models.PROTECT,
        related_name="baseline_memberships",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("execution__question_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("baseline", "execution"),
                name="evaluations_baseline_membership_unique",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Baseline membership is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Baseline membership cannot be deleted.")


class BaselineStateEvent(models.Model):
    """Append-only attribution for active/inactive baseline designation."""

    baseline = models.ForeignKey(
        Baseline,
        on_delete=models.PROTECT,
        related_name="state_history",
    )
    is_active = models.BooleanField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="baseline_state_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Baseline state history is append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Baseline state history cannot be deleted.")


class BaselineAttentionEvent(models.Model):
    """Durable notice that a fixed baseline member became INVALID later."""

    baseline = models.ForeignKey(
        Baseline,
        on_delete=models.PROTECT,
        related_name="attention_events",
    )
    execution = models.ForeignKey(
        Execution,
        on_delete=models.PROTECT,
        related_name="baseline_attention_events",
    )
    validity_decision = models.ForeignKey(
        ExecutionValidityDecision,
        on_delete=models.PROTECT,
        related_name="baseline_attention_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="baseline_attention_events",
    )
    detail = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("baseline", "execution"),
                name="evaluations_baseline_attention_member_unique",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Baseline attention history is append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Baseline attention history cannot be deleted.")


class Comparison(models.Model):
    """One immutable exact-comparison analysis of a controlled Run."""

    baseline = models.ForeignKey(
        Baseline,
        on_delete=models.PROTECT,
        related_name="comparisons",
    )
    current_run = models.OneToOneField(
        EvaluationRun,
        on_delete=models.PROTECT,
        related_name="comparison",
    )
    algorithm_key = models.CharField(max_length=80, default="exact")
    algorithm_version = models.CharField(max_length=80, default="exact-v1")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("baseline", "current_run"),
                name="evaluations_comparison_baseline_run_unique",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Comparison records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Comparison records cannot be deleted.")


class ComparisonItem(models.Model):
    """Immutable M6 exact-comparison result for one historical/current pair."""

    class ChangeState(models.TextChoices):
        UNCHANGED = "UNCHANGED", "Unchanged"
        CHANGED = "CHANGED", "Changed"
        NON_COMPARABLE = "NON_COMPARABLE", "Non-comparable"

    comparison = models.ForeignKey(
        Comparison,
        on_delete=models.PROTECT,
        related_name="items",
    )
    baseline_execution = models.ForeignKey(
        Execution,
        on_delete=models.PROTECT,
        related_name="baseline_comparison_items",
    )
    current_execution = models.ForeignKey(
        Execution,
        on_delete=models.PROTECT,
        related_name="current_comparison_items",
    )
    change_state = models.CharField(max_length=20, choices=ChangeState.choices)
    exact_equal = models.BooleanField(null=True, blank=True)
    baseline_normalized_hash = models.CharField(max_length=64, blank=True)
    current_normalized_hash = models.CharField(max_length=64, blank=True)
    non_comparable_reason = models.CharField(max_length=120, blank=True)
    detail = models.TextField(blank=True)
    performance_policy_version = models.CharField(max_length=80, default="opss-performance-v1")
    baseline_latency_ms = models.PositiveIntegerField(null=True, blank=True)
    current_latency_ms = models.PositiveIntegerField(null=True, blank=True)
    latency_delta_ms = models.IntegerField(null=True, blank=True)
    latency_delta_percent = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    baseline_performance_classification = models.CharField(max_length=16, blank=True)
    current_performance_classification = models.CharField(max_length=16, blank=True)
    performance_change = models.CharField(max_length=16, blank=True)
    performance_band_degraded = models.BooleanField(default=False)
    input_token_delta = models.IntegerField(null=True, blank=True)
    output_token_delta = models.IntegerField(null=True, blank=True)
    total_token_delta = models.IntegerField(null=True, blank=True)
    input_token_delta_percent = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    output_token_delta_percent = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_token_delta_percent = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    baseline_human_review = models.ForeignKey(
        HumanReview,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="baseline_comparison_item_snapshots",
    )
    current_human_review = models.ForeignKey(
        HumanReview,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_comparison_item_snapshots",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("current_execution__question_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("comparison", "current_execution"),
                name="evaluations_comparison_item_current_unique",
            ),
            models.CheckConstraint(
                condition=Q(change_state__in=("UNCHANGED", "CHANGED", "NON_COMPARABLE")),
                name="evaluations_comparison_item_change_state",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Comparison items are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Comparison items cannot be deleted.")


class SemanticComparisonResult(models.Model):
    """One append-only semantic-triage observation for an exact M6 item.

    ``ComparisonItem`` retains M6's immutable exact result.  Semantic results
    form a replacement chain instead: a newer result references the prior
    current result without altering it.  The unsuperseded leaf is the current
    semantic projection for UI triage, while every historical comparator
    conclusion remains available for calibration and explanation.
    """

    class Outcome(models.TextChoices):
        EQUIVALENT = "EQUIVALENT", "Equivalent"
        MATERIAL_CHANGE = "MATERIAL_CHANGE", "Material change"
        UNCERTAIN = "UNCERTAIN", "Uncertain"
        ERROR = "ERROR", "Comparator error"

    comparison_item = models.ForeignKey(
        ComparisonItem,
        on_delete=models.PROTECT,
        related_name="semantic_results",
    )
    supersedes = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_by",
    )
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    provider_key = models.CharField(max_length=100)
    model_identifier = models.CharField(max_length=160)
    comparator_version = models.CharField(max_length=80)
    prompt_version = models.CharField(max_length=80, blank=True)
    input_fingerprint = models.CharField(max_length=64)
    input_manifest = models.JSONField(default=dict, blank=True)
    rationale = models.TextField(blank=True)
    error_class = models.CharField(max_length=100, blank=True)
    error_detail = models.TextField(blank=True)
    raw_result = models.JSONField(default=dict, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=Q(outcome__in=("EQUIVALENT", "MATERIAL_CHANGE", "UNCERTAIN", "ERROR")),
                name="evaluations_semantic_result_outcome",
            ),
        ]
        indexes = [
            models.Index(
                fields=("comparison_item", "-created_at"),
                name="eval_semantic_current_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Semantic comparison results are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Semantic comparison results cannot be deleted.")
