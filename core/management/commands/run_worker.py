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

from evaluations.services import claim_next_execution, process_claim, reconcile_stale_claims


logger = logging.getLogger("stewardbench.worker")


class Command(BaseCommand):
    help = "Run the M4 durable PostgreSQL-backed evaluation worker."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Claim and process at most one Execution, then exit.")
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
        logger.info(
            "M4 worker ready worker_id=%s safe_reclaimed=%s ambiguous=%s",
            worker_id,
            recovered["safe_reclaimed"],
            recovered["ambiguous"],
        )
        if options["once"]:
            claim = claim_next_execution(worker_id)
            if claim:
                process_claim(claim)
            return

        futures = set()
        with ThreadPoolExecutor(max_workers=settings.WORKER_MAX_CONCURRENCY) as executor:
            while not stopping:
                recovered = reconcile_stale_claims()
                if recovered["safe_reclaimed"] or recovered["ambiguous"]:
                    logger.info(
                        "M4 reconciliation worker_id=%s safe_reclaimed=%s ambiguous=%s",
                        worker_id,
                        recovered["safe_reclaimed"],
                        recovered["ambiguous"],
                    )

                while not stopping and len(futures) < settings.WORKER_MAX_CONCURRENCY:
                    claim = claim_next_execution(worker_id)
                    if claim is None:
                        break
                    futures.add(executor.submit(process_claim, claim))

                if futures:
                    done, _ = wait(futures, timeout=settings.WORKER_POLL_SECONDS)
                    futures.difference_update(done)
                    for future in done:
                        try:
                            future.result()
                        except Exception:
                            logger.error("worker task escaped execution isolation worker_id=%s", worker_id)
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
