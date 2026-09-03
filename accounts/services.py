from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import User
from .policy import require_admin


def _validate_role(role):
    if role not in User.Role.values:
        raise ValidationError({"role": "Role must be ADMIN or OPERATOR."})


@transaction.atomic
def create_user(*, actor, username, email, role, password, is_active=True):
    require_admin(actor)
    _validate_role(role)
    user = User(username=username, email=email, role=role, is_active=is_active)
    user.full_clean(exclude={"password"})
    validate_password(password, user=user)
    user.set_password(password)
    user.save()
    return user


@transaction.atomic
def update_user(*, actor, user, email, role, is_active, password=None):
    require_admin(actor)
    _validate_role(role)
    user.email = email
    user.role = role
    user.is_active = is_active
    if password:
        validate_password(password, user=user)
        user.set_password(password)
    user.full_clean()
    user.save()
    return user
