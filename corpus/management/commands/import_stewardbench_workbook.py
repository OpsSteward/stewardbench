import hashlib
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from corpus.mapping import load_mapping
from corpus.reporting import report_as_json, report_as_text
from corpus.services import CorpusImportConflict, apply_import, reconcile_import
from corpus.workbook import inspect_workbook


class Command(BaseCommand):
    help = "Inspect or explicitly apply the approved StewardBench source workbook mapping."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default=str(settings.BASE_DIR / "docs/reference/v2-dev-troubleshooting.xlsx"),
            help="Path to the immutable source workbook.",
        )
        parser.add_argument(
            "--mapping",
            default=str(
                settings.BASE_DIR / "import_mappings/v2_dev_troubleshooting_v1.json"
            ),
            help="Path to the approved repository-controlled mapping fixture.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Inspect and reconcile without database mutation (the default).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Explicitly persist one transactional, idempotent import.",
        )
        parser.add_argument(
            "--actor",
            help="Username of the StewardBench ADMIN executing an applied import.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit the reconciliation report as JSON.",
        )

    def handle(self, *args, **options):
        if options["dry_run"] and options["apply"]:
            raise CommandError("Choose either --dry-run or --apply, not both.")
        apply_requested = options["apply"]
        if apply_requested and not options["actor"]:
            raise CommandError("--actor is required with --apply.")

        workbook_path = Path(options["path"])
        try:
            mapping = load_mapping(options["mapping"])
            plan = inspect_workbook(workbook_path, mapping)
            if apply_requested:
                try:
                    actor = User.objects.get(username=options["actor"])
                except User.DoesNotExist as error:
                    raise CommandError(f"Unknown import actor {options['actor']!r}.") from error
                report = apply_import(plan=plan, actor=actor)
            else:
                report = reconcile_import(plan)
        except CorpusImportConflict as error:
            output = (
                report_as_json(error.report)
                if options["json"]
                else report_as_text(error.report)
            )
            self.stdout.write(output)
            raise CommandError(str(error)) from error
        except (OSError, PermissionDenied, ValidationError) as error:
            message = "; ".join(error.messages) if hasattr(error, "messages") else str(error)
            raise CommandError(message) from error

        final_sha256 = hashlib.sha256(workbook_path.read_bytes()).hexdigest()
        if final_sha256 != plan.source_sha256:
            raise CommandError(
                "The source workbook changed during import; the transaction/report "
                "cannot be trusted."
            )
        report["source"]["sha256_after"] = final_sha256
        output = report_as_json(report) if options["json"] else report_as_text(report)
        self.stdout.write(output)
