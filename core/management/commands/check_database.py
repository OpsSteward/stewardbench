from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Verify that the configured PostgreSQL database is reachable."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        if connection.vendor != "postgresql":
            raise RuntimeError("StewardBench requires PostgreSQL.")
        self.stdout.write("PostgreSQL ready.")
