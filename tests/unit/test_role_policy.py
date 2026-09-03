import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied

from accounts.models import User
from accounts.policy import require_admin


@pytest.mark.django_db
def test_admin_role_is_the_only_product_admin_role(admin_user, operator_user):
    require_admin(admin_user)

    with pytest.raises(PermissionDenied):
        require_admin(operator_user)

    with pytest.raises(PermissionDenied):
        require_admin(AnonymousUser())


@pytest.mark.django_db
def test_framework_flags_do_not_grant_product_admin(operator_user):
    operator_user.is_staff = True
    operator_user.is_superuser = True
    operator_user.save(update_fields=["is_staff", "is_superuser"])

    assert operator_user.role == User.Role.OPERATOR
    with pytest.raises(PermissionDenied):
        require_admin(operator_user)
