import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from accounts.models import User


class Command(BaseCommand):
    help = "Create the first StewardBench ADMIN account without default credentials."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", default="")
        parser.add_argument(
            "--password-env",
            metavar="VARIABLE",
            help="Read the password from this environment variable instead of prompting.",
        )

    def handle(self, *args, **options):
        username = options["username"].strip()
        if not username:
            raise CommandError("Username must not be blank.")

        password_env = options.get("password_env")
        if password_env:
            password = os.environ.get(password_env)
            if not password:
                raise CommandError(f"Password environment variable {password_env} is not set.")
        else:
            password = getpass.getpass("Password: ")
            confirmation = getpass.getpass("Password (again): ")
            if password != confirmation:
                raise CommandError("Passwords do not match.")

        candidate = User(username=username, email=options["email"], role=User.Role.ADMIN)
        try:
            candidate.full_clean(exclude={"password"})
            validate_password(password, user=candidate)
        except ValidationError as error:
            raise CommandError("; ".join(error.messages)) from error

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ["stewardbench:first-admin"])
            if User.objects.filter(role=User.Role.ADMIN).exists():
                raise CommandError("A StewardBench ADMIN already exists; bootstrap made no changes.")
            if User.objects.filter(username=username).exists():
                raise CommandError("That username already exists; bootstrap made no changes.")
            candidate.set_password(password)
            candidate.save()

        self.stdout.write(self.style.SUCCESS(f"Created StewardBench ADMIN {candidate.username}."))
