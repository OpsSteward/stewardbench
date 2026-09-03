from django.contrib.auth import views as auth_views
from django.urls import include, path

from core import views as core_views


urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", core_views.dashboard, name="dashboard"),
    path("health/live/", core_views.liveness, name="health-live"),
    path("health/ready/", core_views.readiness, name="health-ready"),
    path("users/", include("accounts.urls")),
]
