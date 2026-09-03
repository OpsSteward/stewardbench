from django import forms

from catalog.models import EvaluationTarget
from evaluations.models import Baseline, EvaluationRun, Execution, HumanReview


class LaunchRunForm(forms.Form):
    target = forms.ModelChoiceField(
        queryset=EvaluationTarget.objects.none(),
        label="Evaluation target",
    )
    select_all_matching = forms.BooleanField(required=False)
    execution_mode = forms.ChoiceField(
        choices=EvaluationRun.ExecutionMode.choices,
        initial=EvaluationRun.ExecutionMode.SEQUENTIAL,
        label="Execution mode",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target"].queryset = EvaluationTarget.objects.filter(
            is_active=True,
            revisions__valid_to__isnull=True,
            revisions__supports_question_api=True,
        ).distinct().order_by("display_name")


class HumanReviewForm(forms.Form):
    judgment = forms.ChoiceField(choices=HumanReview.Judgment.choices)
    comment = forms.CharField(
        required=False,
        strip=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Optional review context"}),
    )


class CommentForm(forms.Form):
    text = forms.CharField(
        strip=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Append operational context"}),
    )


class ReviewStateForm(forms.Form):
    state = forms.ChoiceField(
        choices=(
            (Execution.ReviewState.REQUIRED, "Mark review required"),
            (Execution.ReviewState.REVIEWED, "Mark reviewed without judgment"),
        )
    )
    comment = forms.CharField(
        required=False,
        strip=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Optional triage context"}),
    )


class ValidityForm(forms.Form):
    validity = forms.ChoiceField(choices=Execution.Validity.choices)
    comment = forms.CharField(
        required=False,
        strip=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Optional invalidation context"}),
    )


class BaselinePromotionForm(forms.Form):
    name = forms.CharField(max_length=180, label="Baseline name")
    description = forms.CharField(
        required=False,
        strip=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Optional historical context"}),
    )
    is_active = forms.BooleanField(
        required=False,
        initial=True,
        label="Make this Baseline active now",
    )


class BaselineStateForm(forms.Form):
    is_active = forms.TypedChoiceField(
        choices=(("true", "Activate"), ("false", "Deactivate")),
        coerce=lambda value: value == "true",
        widget=forms.HiddenInput,
    )


class ControlledComparisonRunForm(forms.Form):
    target = forms.ModelChoiceField(
        queryset=EvaluationTarget.objects.none(),
        label="Current evaluation target",
        help_text="Current target/build identity is frozen at launch; baseline questions and bindings remain historical.",
    )

    def __init__(self, *args, baseline: Baseline | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        targets = EvaluationTarget.objects.filter(
            is_active=True,
            revisions__valid_to__isnull=True,
            revisions__supports_question_api=True,
        ).select_related("product", "environment").distinct().order_by("display_name")
        if baseline is not None:
            targets = targets.filter(
                product_id=baseline.source_target.product_id,
                environment_id=baseline.source_target.environment_id,
            )
        self.fields["target"].queryset = targets
