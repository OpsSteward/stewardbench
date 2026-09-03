from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User


class UserCreateForm(UserCreationForm):
    is_active = forms.BooleanField(required=False, initial=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "role", "is_active")


class UserUpdateForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        strip=False,
        widget=forms.PasswordInput,
        help_text="Leave blank to keep the current password.",
    )

    class Meta:
        model = User
        fields = ("email", "role", "is_active")

    def clean_password(self):
        password = self.cleaned_data["password"]
        if password:
            from django.contrib.auth.password_validation import validate_password

            validate_password(password, user=self.instance)
        return password
