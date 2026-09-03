from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render


@login_required
def dashboard(request):
    return render(request, "core/dashboard.html")


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
