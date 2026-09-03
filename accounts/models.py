from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        OPERATOR = "OPERATOR", "Operator"

    role = models.CharField(max_length=8, choices=Role.choices, default=Role.OPERATOR)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=("ADMIN", "OPERATOR")),
                name="accounts_user_valid_role",
            )
        ]

    @property
    def is_stewardbench_admin(self):
        return self.is_active and self.role == self.Role.ADMIN
