"""PostgreSQL acceptance for M10's independent performance/efficiency evidence."""

from __future__ import annotations

import csv
import io
import json

import pytest
from django.urls import reverse
from django.utils import timezone

from catalog.models import Question, TargetRevision
from catalog.services import create_question, create_target_revision
from evaluations.models import Execution
from evaluations.performance import PERFORMANCE_POLICY_VERSION, classify_latency
from evaluations.services import (
    append_execution_comment,
    create_baseline,
    launch_controlled_comparison,
    launch_run,
    mark_review_required,
    process_next_execution,
    record_exact_comparison,
    record_human_review,
    set_execution_validity,
)
from harness.fake_target import FakeTargetServer


def _revision(endpoint):
    return {
        "endpoint": endpoint, "adapter_key": "fake-http", "adapter_version": "1", "credential_reference": "",
        "classification": TargetRevision.Classification.LAB_TEST, "supports_question_api": True,
        "supports_conversation_session": False, "supports_runtime_metadata": False, "supports_health_check": True,
        "default_execution_mode": TargetRevision.ExecutionMode.SEQUENTIAL, "max_concurrency": 1,
        "question_timeout_seconds": 2, "inter_question_delay_seconds": 0,
        "declared_product_version": "m10-performance", "declared_build_id": "m10-build", "declared_git_sha": "m10-sha",
    }


def _terminal_fixture_update(execution, *, answer, latency_ms, tokens, runtime="vLLM", model="fixture-model"):
    """Prepare an exact, already captured observation for controlled-pair truth.

    The direct update is fixture setup, not a supported product mutation.  It
    gives PostgreSQL a deterministic integer latency without pretending a
    wall-clock sleep can prove a 1000/1001 ms policy boundary.
    """

    now = timezone.now()
    Execution.objects.filter(pk=execution.pk).update(
        outcome=Execution.Outcome.SUCCESS, target_call_phase=Execution.TargetCallPhase.TERMINAL,
        raw_response=json.dumps({"answer": answer}), raw_answer=answer, display_answer=answer,
        started_at=now, completed_at=now, latency_ms=latency_ms,
        performance_policy_version=PERFORMANCE_POLICY_VERSION,
        performance_classification=classify_latency(latency_ms),
        input_tokens=tokens[0], output_tokens=tokens[1], total_tokens=tokens[2],
        token_usage_metadata={"source": "TARGET_REPORTED"},
        runtime_telemetry={"provider_or_runtime": runtime, "model": model},
        internal_timing_metadata={"routing_ms": 7},
    )
    execution.refresh_from_db()
    return execution


def _controlled_pair(minimal_domain, fake, *, baseline_latency, current_latency, baseline_tokens, current_tokens, baseline_answer="A", current_answer="A", baseline_human="GOOD", current_human="GOOD"):
    create_target_revision(actor=minimal_domain["admin"], target=minimal_domain["target"], **_revision(fake.endpoint))
    fake.state.configure(answer=baseline_answer)
    source_run = launch_run(actor=minimal_domain["admin"], target=minimal_domain["target"], question_ids=[minimal_domain["question"].pk])
    assert process_next_execution()
    baseline_execution = _terminal_fixture_update(source_run.executions.get(), answer=baseline_answer, latency_ms=baseline_latency, tokens=baseline_tokens)
    record_human_review(actor=minimal_domain["admin"], execution=baseline_execution, judgment=baseline_human)
    baseline = create_baseline(
        actor=minimal_domain["admin"],
        source_run=source_run,
        name=f"M10 baseline {baseline_latency} {source_run.pk}",
    )
    current_run = launch_controlled_comparison(actor=minimal_domain["admin"], baseline=baseline, target=minimal_domain["target"])
    current = _terminal_fixture_update(current_run.executions.get(), answer=current_answer, latency_ms=current_latency, tokens=current_tokens)
    record_human_review(actor=minimal_domain["admin"], execution=current, judgment=current_human)
    item = record_exact_comparison(current_execution=current)
    assert item is not None
    baseline_execution.refresh_from_db()
    current.refresh_from_db()
    return baseline_execution, current, item, current_run


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_perf_001_quality_performance_timeout_dashboard_and_drilldown(client, minimal_domain):
    """ACC-PERF-001: DB IDs prove quality/performance are orthogonal and timeout is separate."""

    with FakeTargetServer() as fake:
        create_target_revision(actor=minimal_domain["admin"], target=minimal_domain["target"], **_revision(fake.endpoint))
        slow_question = create_question(actor=minimal_domain["admin"], stable_id="M10-SLOW", kind=Question.Kind.SINGLE_TURN, lifecycle=Question.Lifecycle.ACTIVE, domain=minimal_domain["domain"], tags=(), rationale="", question_text="Slow but accurate?")
        timeout_question = create_question(actor=minimal_domain["admin"], stable_id="M10-TIMEOUT", kind=Question.Kind.SINGLE_TURN, lifecycle=Question.Lifecycle.ACTIVE, domain=minimal_domain["domain"], tags=(), rationale="", question_text="Timeout fixture?")
        run = launch_run(actor=minimal_domain["admin"], target=minimal_domain["target"], question_ids=[minimal_domain["question"].pk, slow_question.pk, timeout_question.pk])
        assert process_next_execution() and process_next_execution() and process_next_execution()
        fast, slow, timed_out = list(run.executions.order_by("question_order"))
        _terminal_fixture_update(fast, answer="fast but inaccurate", latency_ms=800, tokens=(None, None, None))
        _terminal_fixture_update(slow, answer="slow but accurate", latency_ms=11000, tokens=(10, 20, 30))
        Execution.objects.filter(pk=timed_out.pk).update(outcome=Execution.Outcome.TIMEOUT, performance_classification="", latency_ms=15000)
        timed_out.refresh_from_db()
        record_human_review(actor=minimal_domain["admin"], execution=fast, judgment="BAD")
        record_human_review(actor=minimal_domain["admin"], execution=slow, judgment="GOOD")
        mark_review_required(actor=minimal_domain["admin"], execution=timed_out, cause="M10 timeout attention")
        client.force_login(minimal_domain["admin"])

        expected_bad = list(Execution.objects.filter(outcome="SUCCESS", validity="VALID", performance_classification="BAD").values_list("pk", flat=True))
        expected_timeout = list(Execution.objects.filter(outcome="TIMEOUT").values_list("pk", flat=True))
        expected_quality_bad = list(Execution.objects.filter(current_human_review__judgment="BAD").values_list("pk", flat=True))
        assert expected_bad == [slow.pk]
        assert expected_timeout == [timed_out.pk]
        assert expected_quality_bad == [fast.pk]
        dashboard = client.get(reverse("dashboard"))
        assert dashboard.status_code == 200
        assert f'?performance=BAD">{len(expected_bad)}'.encode() in dashboard.content
        assert f'?outcome=TIMEOUT">{len(expected_timeout)}'.encode() in dashboard.content
        assert [row.pk for row in client.get(reverse("execution-list"), {"performance": "BAD"}).context["page"].object_list] == expected_bad
        assert [row.pk for row in client.get(reverse("execution-list"), {"outcome": "TIMEOUT"}).context["page"].object_list] == expected_timeout
        assert [row.pk for row in client.get(reverse("execution-list"), {"human": "BAD"}).context["page"].object_list] == expected_quality_bad
        assert [row.pk for row in client.get(reverse("execution-list"), {"human": "GOOD", "performance": "BAD"}).context["page"].object_list] == [slow.pk]
        assert [row.pk for row in client.get(reverse("execution-list"), {"domain": "network-operations", "performance": "BAD"}).context["page"].object_list] == [slow.pk]
        assert [row.pk for row in client.get(reverse("execution-list"), {"build": "m10-sha", "performance": "BAD"}).context["page"].object_list] == [slow.pk]
        assert timed_out.performance_classification == ""


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_perf_002_controlled_pair_export_filter_and_immutability(client, minimal_domain):
    """ACC-PERF-002: a controlled pair persists raw performance/token dimensions and exports them."""

    with FakeTargetServer() as fake:
        baseline, current, item, current_run = _controlled_pair(
            minimal_domain, fake, baseline_latency=9400, current_latency=3170,
            baseline_tokens=(1800, 3011, 4811), current_tokens=(900, 1367, 2267),
        )
        item.refresh_from_db()
        assert (baseline.current_human_review.judgment, current.current_human_review.judgment) == ("GOOD", "GOOD")
        assert (item.baseline_latency_ms, item.current_latency_ms, item.latency_delta_ms) == (9400, 3170, -6230)
        assert str(item.latency_delta_percent) == "-66.28"
        assert (item.baseline_performance_classification, item.current_performance_classification, item.performance_change) == ("SLOW", "ACCEPTABLE", "IMPROVED")
        assert item.performance_band_degraded is False
        assert (item.total_token_delta, str(item.total_token_delta_percent)) == (-2544, "-52.88")
        fingerprint = (current.latency_ms, current.input_tokens, current.output_tokens, current.total_tokens, current.runtime_telemetry, current.internal_timing_metadata)
        record_human_review(actor=minimal_domain["admin"], execution=current, judgment="GOOD", comment_text="M10 evidence remains immutable")
        append_execution_comment(actor=minimal_domain["admin"], execution=current, text="Append-only M10 evidence context")
        set_execution_validity(actor=minimal_domain["admin"], execution=current, validity=Execution.Validity.INVALID, comment_text="Fixture invalidation")
        set_execution_validity(actor=minimal_domain["admin"], execution=current, validity=Execution.Validity.VALID, comment_text="Fixture correction")
        current.refresh_from_db()
        assert (current.latency_ms, current.input_tokens, current.output_tokens, current.total_tokens, current.runtime_telemetry, current.internal_timing_metadata) == fingerprint
        client.force_login(minimal_domain["operator"])
        payload = json.loads(client.get(reverse("run-json-export", args=[current_run.pk])).content)
        exported = next(entry for entry in payload["executions"] if entry["id"] == current.pk)
        assert exported["observation"]["timing"]["observed_latency_ms"] == 3170
        assert exported["observation"]["performance"]["classification"] == "ACCEPTABLE"
        assert exported["observation"]["efficiency"]["total_tokens"] == 2267
        assert exported["observation"]["runtime_telemetry"]["model"] == "fixture-model"
        comparison = exported["comparison_items"][0]
        assert comparison["performance"]["latency_delta_ms"] == -6230
        assert comparison["efficiency"]["total_token_delta"] == -2544

        detail = client.get(reverse("execution-detail", args=[current.pk]))
        assert detail.status_code == 200
        assert b"Observed response latency" in detail.content
        assert b"9400 ms" in detail.content and b"3170 ms" in detail.content
        comparison_detail = client.get(reverse("comparison-detail", args=[item.comparison_id]))
        assert comparison_detail.status_code == 200
        assert b"Performance / latency" in comparison_detail.content
        assert b"SLOW \xe2\x86\x92 ACCEPTABLE" in comparison_detail.content

        csv_rows = list(csv.DictReader(io.StringIO(client.get(reverse("execution-csv-export"), {"human": "GOOD", "performance": "ACCEPTABLE"}).content.decode())))
        assert [int(row["execution_id"]) for row in csv_rows] == [current.pk]
        assert csv_rows[0]["observed_latency_ms"] == "3170"
        assert csv_rows[0]["total_tokens"] == "2267"
        comparison_csv = list(csv.DictReader(io.StringIO(client.get(reverse("comparison-csv-export", args=[item.comparison_id])).content.decode())))
        assert len(comparison_csv) == 1
        # CSV protects spreadsheet consumers from formula-like leading minus;
        # the JSON assertion above retains these values as numeric evidence.
        assert comparison_csv[0]["latency_delta_ms"] == "'-6230"
        assert comparison_csv[0]["total_token_delta"] == "'-2544"

        _, regressed_current, regressed_item, _ = _controlled_pair(
            minimal_domain, fake, baseline_latency=3000, current_latency=6000,
            baseline_tokens=(1000, 1000, 2000), current_tokens=(1000, 1000, 5000),
        )
        regressed_item.refresh_from_db()
        assert (regressed_item.change_state, regressed_item.performance_change) == ("UNCHANGED", "REGRESSED")
        assert (regressed_item.baseline_performance_classification, regressed_item.current_performance_classification) == ("ACCEPTABLE", "SLOW")
        assert regressed_item.performance_band_degraded is True
        assert (regressed_item.total_token_delta, str(regressed_item.total_token_delta_percent)) == (3000, "150.00")
        matching = client.get(reverse("execution-list"), {"change": "UNCHANGED", "performance_change": "REGRESSED"})
        assert [row.pk for row in matching.context["page"].object_list] == [regressed_current.pk]

        # Conflicting quality/performance changes remain independently visible;
        # no persistent composite verdict exists to hide either trade-off.
        quality_improved_baseline, quality_improved_current, quality_improved_item, _ = _controlled_pair(
            minimal_domain, fake, baseline_latency=3000, current_latency=9000,
            baseline_tokens=(1000, 1000, 2000), current_tokens=(1000, 1000, 2000),
            baseline_answer="quality-before", current_answer="quality-after",
            baseline_human="BAD", current_human="GOOD",
        )
        assert (
            quality_improved_baseline.current_human_review.judgment,
            quality_improved_current.current_human_review.judgment,
            quality_improved_item.performance_change,
            quality_improved_item.performance_band_degraded,
        ) == ("BAD", "GOOD", "REGRESSED", True)

        quality_regressed_baseline, quality_regressed_current, quality_regressed_item, _ = _controlled_pair(
            minimal_domain, fake, baseline_latency=9000, current_latency=900,
            baseline_tokens=(1000, 1000, 2000), current_tokens=(1000, 1000, 2000),
            baseline_answer="quality-good", current_answer="quality-bad",
            baseline_human="GOOD", current_human="BAD",
        )
        assert (
            quality_regressed_baseline.current_human_review.judgment,
            quality_regressed_current.current_human_review.judgment,
            quality_regressed_item.performance_change,
            quality_regressed_item.baseline_performance_classification,
            quality_regressed_item.current_performance_classification,
        ) == ("GOOD", "BAD", "IMPROVED", "SLOW", "TARGET")

        _, unknown_tokens_current, unknown_tokens_item, _ = _controlled_pair(
            minimal_domain, fake, baseline_latency=3000, current_latency=3000,
            baseline_tokens=(1000, 2000, 3000), current_tokens=(None, None, None),
            baseline_answer="tokens-known", current_answer="tokens-unknown",
        )
        assert unknown_tokens_current.total_tokens is None
        assert (
            unknown_tokens_item.input_token_delta,
            unknown_tokens_item.output_token_delta,
            unknown_tokens_item.total_token_delta,
            unknown_tokens_item.total_token_delta_percent,
        ) == (None, None, None, None)


@pytest.mark.acceptance
@pytest.mark.django_db
def test_acc_eff_001_optional_telemetry_is_postgresql_evidence_not_answer_failure(client, minimal_domain):
    """ACC-EFF-001: target-reported telemetry persists; malformed optional values stay unknown."""

    with FakeTargetServer() as fake:
        create_target_revision(actor=minimal_domain["admin"], target=minimal_domain["target"], **_revision(fake.endpoint))
        fake.state.configure(answer="telemetry answer", delay_seconds=0.02, telemetry={"usage": {"input_tokens": 1000, "output_tokens": 2000, "total_tokens": 3000}, "runtime": {"provider_or_runtime": "<script>runtime</script>", "model": "=synthetic-model"}, "internal_timings": {"routing_ms": 4}})
        first = launch_run(actor=minimal_domain["admin"], target=minimal_domain["target"], question_ids=[minimal_domain["question"].pk])
        assert process_next_execution()
        observed = first.executions.get()
        assert (observed.input_tokens, observed.output_tokens, observed.total_tokens) == (1000, 2000, 3000)
        assert observed.runtime_telemetry == {"provider_or_runtime": "<script>runtime</script>", "model": "=synthetic-model"}
        assert observed.internal_timing_metadata == {"routing_ms": 4}
        journal = fake.state.journal_snapshot()
        assert len(journal["entries"]) == 1
        assert journal["entries"][0]["response_delay_seconds"] == 0.02
        assert observed.latency_ms >= 10  # wall-clock tolerance; policy boundaries are pure integer tests.
        client.force_login(minimal_domain["operator"])
        detail = client.get(reverse("execution-detail", args=[observed.pk]))
        assert b"&lt;script&gt;runtime&lt;/script&gt;" in detail.content
        assert b"<script>runtime</script>" not in detail.content
        rows = list(csv.DictReader(io.StringIO(client.get(reverse("execution-csv-export")).content.decode())))
        row = next(row for row in rows if int(row["execution_id"]) == observed.pk)
        assert row["model"] == "'=synthetic-model"
        exported = json.loads(client.get(reverse("run-json-export", args=[first.pk])).content)
        assert exported["executions"][0]["observation"]["runtime_telemetry"]["model"] == "=synthetic-model"

        fake.state.configure(answer="still valid", telemetry={"usage": {"input_tokens": "no", "output_tokens": -1, "total_tokens": True}, "runtime": {"model": 5}, "internal_timings": {"routing_ms": "no"}})
        second = launch_run(actor=minimal_domain["admin"], target=minimal_domain["target"], question_ids=[minimal_domain["question"].pk])
        assert process_next_execution()
        malformed = second.executions.get()
        assert malformed.outcome == Execution.Outcome.SUCCESS
        assert malformed.display_answer == "still valid"
        assert (malformed.input_tokens, malformed.output_tokens, malformed.total_tokens) == (None, None, None)
        assert "malformed_total_tokens" in malformed.token_usage_metadata["diagnostics"]
        assert malformed.internal_timing_metadata == {}
