import pytest
from django.db import IntegrityError, transaction

from accounts.models import User


@pytest.mark.django_db
@pytest.mark.postgresql
def test_database_rejects_unsupported_product_role(operator_user):
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=operator_user.pk).update(role="REVIEWER")

    operator_user.refresh_from_db()
    assert operator_user.role == User.Role.OPERATOR


@pytest.mark.django_db
@pytest.mark.postgresql
def test_users_have_exactly_one_product_role(db):
    user = User.objects.create_user(username="default-role", password="Default-Role-Password-42!")
    assert user.role == User.Role.OPERATOR
    assert set(User.Role.values) == {"ADMIN", "OPERATOR"}
