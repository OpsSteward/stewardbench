from django import forms
from django.forms import formset_factory

from .models import (
    BindingDefinition,
    Domain,
    Environment,
    HistoricalFixture,
    Product,
    Question,
    QuestionVersion,
    Tag,
    TargetRevision,
)


class ProductCreateForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ("slug", "display_name", "description", "is_active")


class ProductUpdateForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ("display_name", "description", "is_active")


class EnvironmentCreateForm(forms.ModelForm):
    class Meta:
        model = Environment
        fields = ("slug", "display_name", "description", "is_active")


class EnvironmentUpdateForm(forms.ModelForm):
    class Meta:
        model = Environment
        fields = ("display_name", "description", "is_active")


class DomainCreateForm(forms.ModelForm):
    class Meta:
        model = Domain
        fields = ("slug", "name", "description", "is_active")


class DomainUpdateForm(forms.ModelForm):
    class Meta:
        model = Domain
        fields = ("name", "description", "is_active")


class TagCreateForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ("name",)


class HistoricalFixtureForm(forms.ModelForm):
    class Meta:
        model = HistoricalFixture
        fields = (
            "stable_id",
            "name",
            "environment",
            "window_start",
            "window_end",
            "description",
            "tags",
            "fixed_parameters",
            "is_active",
        )
        widgets = {
            "window_start": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "window_end": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }


class TargetIdentityForm(forms.Form):
    slug = forms.SlugField(max_length=100)
    display_name = forms.CharField(max_length=180)
    product = forms.ModelChoiceField(queryset=Product.objects.all())
    environment = forms.ModelChoiceField(queryset=Environment.objects.all())
    is_active = forms.BooleanField(required=False, initial=True)


class TargetUpdateForm(forms.Form):
    display_name = forms.CharField(max_length=180)
    is_active = forms.BooleanField(required=False)


class TargetRevisionForm(forms.ModelForm):
    endpoint = forms.URLField(max_length=500, assume_scheme="https")

    class Meta:
        model = TargetRevision
        fields = (
            "endpoint",
            "adapter_key",
            "adapter_version",
            "credential_reference",
            "classification",
            "supports_question_api",
            "supports_conversation_session",
            "supports_runtime_metadata",
            "supports_health_check",
            "default_execution_mode",
            "max_concurrency",
            "question_timeout_seconds",
            "inter_question_delay_seconds",
            "declared_product_version",
            "declared_build_id",
            "declared_git_sha",
        )


class QuestionCreateForm(forms.Form):
    stable_id = forms.CharField(max_length=120)
    kind = forms.ChoiceField(choices=Question.Kind.choices)
    lifecycle = forms.ChoiceField(choices=Question.Lifecycle.choices)
    domain = forms.ModelChoiceField(queryset=Domain.objects.all(), required=False)
    tags = forms.ModelMultipleChoiceField(queryset=Tag.objects.all(), required=False)
    rationale = forms.CharField(widget=forms.Textarea, required=False)
    question_text = forms.CharField(widget=forms.Textarea)
    evaluation_guidance = forms.CharField(widget=forms.Textarea, required=False)


class QuestionMetadataForm(forms.Form):
    domain = forms.ModelChoiceField(queryset=Domain.objects.all(), required=False)
    tags = forms.ModelMultipleChoiceField(queryset=Tag.objects.all(), required=False)
    rationale = forms.CharField(widget=forms.Textarea, required=False)


class QuestionVersionForm(forms.Form):
    question_text = forms.CharField(widget=forms.Textarea)
    evaluation_guidance = forms.CharField(widget=forms.Textarea, required=False)
    change_type = forms.ChoiceField(
        choices=(("", "Not classified"), *QuestionVersion.ChangeType.choices),
        required=False,
    )
    change_reason = forms.CharField(widget=forms.Textarea, required=False)


class BindingDefinitionInputForm(forms.Form):
    name = forms.CharField(max_length=80, required=False)
    value_type = forms.ChoiceField(
        choices=BindingDefinition.ValueType.choices,
        required=False,
    )
    is_required = forms.BooleanField(required=False, initial=True)
    description = forms.CharField(widget=forms.Textarea, required=False)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("name") and not cleaned.get("value_type"):
            self.add_error("value_type", "Choose the expected value shape.")
        if not cleaned.get("name") and any(
            cleaned.get(field) for field in ("value_type", "description")
        ):
            self.add_error("name", "Enter a binding name or clear the row.")
        return cleaned


BindingDefinitionFormSet = formset_factory(
    BindingDefinitionInputForm,
    extra=1,
    can_delete=True,
)
