from django.urls import path

from . import views


urlpatterns = [
    path("", views.user_list, name="user-list"),
    path("new/", views.user_create, name="user-create"),
    path("<int:pk>/edit/", views.user_update, name="user-update"),
]
