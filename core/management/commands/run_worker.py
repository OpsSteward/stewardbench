import logging
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from evaluations.services import process_next_execution, recover_interrupted_executions


logger = logging.getLogger("stewardbench.worker")


class Command(BaseCommand):
    help = "Run the M3 sequential PostgreSQL-backed evaluation worker."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Check readiness and exit.")

    def handle(self, *args, **options):
        stopping = False

        def stop(signum, frame):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        self._check_database()
        recovered = recover_interrupted_executions()
        logger.info("M3 sequential worker ready; marked %s interrupted execution(s) ambiguous.", recovered)
        if options["once"]:
            process_next_execution()
            return

        while not stopping:
            if not process_next_execution():
                time.sleep(settings.WORKER_POLL_SECONDS)
            self._check_database()

        logger.info("M3 sequential worker stopped.")

    @staticmethod
    def _check_database():
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
