"""Dedicated M4 PostgreSQL worker process entry point."""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from evaluations.services import (
    claim_next_evaluation_invocation,
    claim_next_execution,
    process_claim,
    process_evaluation_invocation,
    reconcile_stale_evaluation_invocations,
    reconcile_stale_claims,
)


logger = logging.getLogger("stewardbench.worker")


class Command(BaseCommand):
    help = "Run the M4 durable PostgreSQL-backed evaluation worker."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Claim and process at most one target Execution or evaluator invocation, then exit.",
        )
        parser.add_argument(
            "--worker-id",
            default="",
            help="Optional diagnostic identity. Normal workers generate a unique identity.",
        )

    def handle(self, *args, **options):
        stopping = False
        worker_id = options["worker_id"] or self._worker_id()

        def stop(signum, frame):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        self._check_database()
        recovered = reconcile_stale_claims()
        evaluator_recovered = reconcile_stale_evaluation_invocations()
        logger.info(
            "M4/M9 worker ready worker_id=%s safe_reclaimed=%s ambiguous=%s evaluator_requeued=%s",
            worker_id,
            recovered["safe_reclaimed"],
            recovered["ambiguous"],
            evaluator_recovered,
        )
        if options["once"]:
            claim = claim_next_execution(worker_id)
            if claim:
                process_claim(claim)
            else:
                evaluation_claim = claim_next_evaluation_invocation(worker_id)
                if evaluation_claim:
                    process_evaluation_invocation(evaluation_claim)
            return

        futures = set()
        evaluator_futures = set()
        with (
            ThreadPoolExecutor(max_workers=settings.WORKER_MAX_CONCURRENCY) as executor,
            ThreadPoolExecutor(max_workers=settings.EVALUATOR_WORKER_MAX_CONCURRENCY) as evaluator_executor,
        ):
            while not stopping:
                recovered = reconcile_stale_claims()
                evaluator_recovered = reconcile_stale_evaluation_invocations()
                if recovered["safe_reclaimed"] or recovered["ambiguous"]:
                    logger.info(
                        "M4 reconciliation worker_id=%s safe_reclaimed=%s ambiguous=%s",
                        worker_id,
                        recovered["safe_reclaimed"],
                        recovered["ambiguous"],
                    )
                if evaluator_recovered:
                    logger.info("M9 evaluator reconciliation worker_id=%s requeued=%s", worker_id, evaluator_recovered)

                while not stopping and len(futures) < settings.WORKER_MAX_CONCURRENCY:
                    claim = claim_next_execution(worker_id)
                    if claim is None:
                        break
                    futures.add(executor.submit(process_claim, claim))

                # M9 calls use a separate resource pool.  Judge/provider
                # latency therefore cannot occupy target capacity or change the
                # target claim/concurrency calculations.
                while not stopping and len(evaluator_futures) < settings.EVALUATOR_WORKER_MAX_CONCURRENCY:
                    evaluation_claim = claim_next_evaluation_invocation(worker_id)
                    if evaluation_claim is None:
                        break
                    evaluator_futures.add(evaluator_executor.submit(process_evaluation_invocation, evaluation_claim))

                if futures or evaluator_futures:
                    done, _ = wait(futures | evaluator_futures, timeout=settings.WORKER_POLL_SECONDS)
                    target_done = done & futures
                    futures.difference_update(target_done)
                    for future in target_done:
                        try:
                            future.result()
                        except Exception:
                            logger.error("worker task escaped execution isolation worker_id=%s", worker_id)
                    evaluator_done = done & evaluator_futures
                    evaluator_futures.difference_update(evaluator_done)
                    for future in evaluator_done:
                        try:
                            future.result()
                        except Exception:
                            logger.error("worker task escaped evaluator isolation worker_id=%s", worker_id)
                else:
                    time.sleep(settings.WORKER_POLL_SECONDS)
                self._check_database()

        logger.info("M4 worker stopped worker_id=%s", worker_id)

    @staticmethod
    def _worker_id():
        return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"

    @staticmethod
    def _check_database():
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
