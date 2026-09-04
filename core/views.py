from django.contrib.auth.decorators import login_required
from django.db import connection
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render

from accounts.policy import require_admin
from evaluations.reporting import automated_readiness, dashboard_projection, target_adapter_statuses, worker_readiness


@login_required
def dashboard(request):
    return render(request, "core/dashboard.html", dashboard_projection())


@login_required
def operational_status(request):
    """Small ADMIN-only readiness view; it is intentionally not a monitor."""

    require_admin(request.user)
    return render(
        request,
        "core/operational_status.html",
        {
            "adapter_rows": target_adapter_statuses(),
            "automated": automated_readiness(),
            "worker": worker_readiness(),
            "database_status": "PostgreSQL configured",
            "application_version": settings.STEWARD_BENCH_APPLICATION_VERSION,
        },
    )


@login_required
def liveness(request):
    return JsonResponse({"status": "alive"})


@login_required
def readiness(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "not-ready"}, status=503)
    return JsonResponse({"status": "ready", "database": "postgresql"})
