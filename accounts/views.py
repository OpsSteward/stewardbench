from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from .forms import UserCreateForm, UserUpdateForm
from .models import User
from .policy import require_admin
from .services import create_user, update_user


def _admin_required(request):
    require_admin(request.user)


@login_required
def user_list(request):
    _admin_required(request)
    return render(request, "accounts/user_list.html", {"users": User.objects.order_by("username")})


@login_required
def user_create(request):
    _admin_required(request)
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            user = create_user(
                actor=request.user,
                username=form.cleaned_data["username"],
                email=form.cleaned_data["email"],
                role=form.cleaned_data["role"],
                password=form.cleaned_data["password1"],
                is_active=form.cleaned_data["is_active"],
            )
        except (PermissionDenied, ValidationError) as error:
            form.add_error(None, error)
        else:
            messages.success(request, f"User {user.username} created.")
            return redirect("user-list")
    return render(request, "accounts/user_form.html", {"form": form, "heading": "Create user"})


@login_required
def user_update(request, pk):
    _admin_required(request)
    user = get_object_or_404(User, pk=pk)
    form = UserUpdateForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        try:
            update_user(
                actor=request.user,
                user=user,
                email=form.cleaned_data["email"],
                role=form.cleaned_data["role"],
                is_active=form.cleaned_data["is_active"],
                password=form.cleaned_data["password"] or None,
            )
        except (PermissionDenied, ValidationError) as error:
            form.add_error(None, error)
        else:
            messages.success(request, f"User {user.username} updated.")
            return redirect("user-list")
    return render(
        request,
        "accounts/user_form.html",
        {"form": form, "heading": f"Edit {user.username}", "managed_user": user},
    )
