import logging
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


logger = logging.getLogger("stewardbench.worker")


class Command(BaseCommand):
    help = "Run the M0 PostgreSQL-connected idle worker foundation."

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
        logger.info("Worker foundation ready; no evaluation work exists in M0.")
        if options["once"]:
            return

        while not stopping:
            time.sleep(settings.WORKER_POLL_SECONDS)
            self._check_database()

        logger.info("Worker foundation stopped.")

    @staticmethod
    def _check_database():
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
