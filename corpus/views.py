from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from .models import LegacyImportBatch, LegacyObservation


@login_required
def import_batch_list(request):
    batches = LegacyImportBatch.objects.select_related("imported_by")
    return render(request, "corpus/import_batch_list.html", {"batches": batches})


@login_required
def import_batch_detail(request, pk):
    batch = get_object_or_404(
        LegacyImportBatch.objects.select_related("imported_by"), pk=pk
    )
    source_rows = batch.source_rows.select_related("domain", "question", "question_version")
    page = Paginator(source_rows, 50).get_page(request.GET.get("page"))
    observations = LegacyObservation.objects.filter(source_row__batch=batch).select_related(
        "source_row", "question"
    )
    return render(
        request,
        "corpus/import_batch_detail.html",
        {
            "batch": batch,
            "page": page,
            "observations": observations,
            "warnings": batch.warnings.all(),
            "domain_mappings": batch.mapping_snapshot["sheets"]["target questions"][
                "domains"
            ],
        },
    )


@login_required
def legacy_observation_detail(request, pk):
    observation = get_object_or_404(
        LegacyObservation.objects.select_related(
            "source_row__batch", "question", "question_version"
        ).prefetch_related("source_row__source_cells"),
        pk=pk,
    )
    return render(
        request,
        "corpus/legacy_observation_detail.html",
        {"observation": observation},
    )
