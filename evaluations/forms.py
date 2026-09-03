from django import forms

from catalog.models import EvaluationTarget


class LaunchRunForm(forms.Form):
    target = forms.ModelChoiceField(
        queryset=EvaluationTarget.objects.none(),
        label="Evaluation target",
    )
    select_all_matching = forms.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target"].queryset = EvaluationTarget.objects.filter(
            is_active=True,
            revisions__valid_to__isnull=True,
            revisions__supports_question_api=True,
        ).distinct().order_by("display_name")
