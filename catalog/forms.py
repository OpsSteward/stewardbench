from django import forms
from django.forms import formset_factory

from .models import (
    BindingDefinition,
    ConversationScenario,
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
    kind = forms.ChoiceField(choices=((Question.Kind.SINGLE_TURN, "Single turn"),))
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


class ConversationScenarioForm(forms.Form):
    stable_id = forms.CharField(max_length=120)
    name = forms.CharField(max_length=180)
    description = forms.CharField(widget=forms.Textarea, required=False)
    lifecycle = forms.ChoiceField(choices=ConversationScenario.Lifecycle.choices)
    domain = forms.ModelChoiceField(queryset=Domain.objects.all(), required=False)
    tags = forms.ModelMultipleChoiceField(queryset=Tag.objects.all(), required=False)
    definition = forms.CharField(
        widget=forms.Textarea,
        required=False,
        help_text="Version-bound execution rationale or expected session behavior.",
    )


class ConversationScenarioMetadataForm(forms.Form):
    name = forms.CharField(max_length=180)
    description = forms.CharField(widget=forms.Textarea, required=False)
    lifecycle = forms.ChoiceField(choices=ConversationScenario.Lifecycle.choices)
    domain = forms.ModelChoiceField(queryset=Domain.objects.all(), required=False)
    tags = forms.ModelMultipleChoiceField(queryset=Tag.objects.all(), required=False)


class ConversationScenarioVersionForm(forms.Form):
    definition = forms.CharField(
        widget=forms.Textarea,
        required=False,
        help_text="Version-bound execution rationale or expected session behavior.",
    )


class ConversationTurnInputForm(forms.Form):
    prompt_template = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}),
        required=False,
        help_text="Required unless a canonical QuestionVersion is selected.",
    )
    canonical_question_version = forms.ModelChoiceField(
        queryset=QuestionVersion.objects.filter(
            question__kind=Question.Kind.SINGLE_TURN
        ).select_related("question"),
        required=False,
        help_text="Use the exact canonical text instead of duplicating an existing Question.",
    )
    static_bindings = forms.JSONField(required=False, initial=dict)
    required_for_overall = forms.BooleanField(required=False, initial=True)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("prompt_template", "").strip() and not cleaned.get("canonical_question_version"):
            # ``required_for_overall`` has a True initial value.  It must not
            # turn every unused extra form into a phantom turn validation
            # error; only actual prompt/binding content makes the row active.
            if cleaned.get("static_bindings") not in (None, {}):
                self.add_error("prompt_template", "Enter a prompt or choose a canonical QuestionVersion.")
            return cleaned
        bindings = cleaned.get("static_bindings") or {}
        if not isinstance(bindings, dict):
            self.add_error("static_bindings", "Static bindings must be an object.")
        return cleaned


ConversationTurnFormSet = formset_factory(ConversationTurnInputForm, extra=8, can_delete=True)


class BindingDefinitionInputForm(forms.Form):
    name = forms.CharField(max_length=80, required=False)
    value_type = forms.ChoiceField(
        choices=BindingDefinition.ValueType.choices,
        required=False,
    )
    is_required = forms.BooleanField(required=False, initial=True)
    description = forms.CharField(widget=forms.Textarea, required=False)
    fixed_value = forms.JSONField(
        required=False,
        help_text="Optional non-secret fixed value used for {{binding_name}} in M3.",
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("name") and not cleaned.get("value_type"):
            self.add_error("value_type", "Choose the expected value shape.")
        if not cleaned.get("name") and any(
            cleaned.get(field) for field in ("value_type", "description", "fixed_value")
        ):
            self.add_error("name", "Enter a binding name or clear the row.")
        if cleaned.get("name") and any(
            fragment in cleaned["name"].casefold()
            for fragment in ("password", "secret", "token", "authorization", "cookie")
        ):
            self.add_error("name", "Binding names cannot be credential-shaped.")
        return cleaned


BindingDefinitionFormSet = formset_factory(
    BindingDefinitionInputForm,
    extra=1,
    can_delete=True,
)
