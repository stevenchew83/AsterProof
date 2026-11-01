"""Admin-private, synthetic-only review workspace; no provider or publication actions."""

import uuid

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from inspinia.solutions.assessment_contracts import MODES
from inspinia.solutions.evaluation_contracts import EvaluationDataError
from inspinia.solutions.prototype_models import SyntheticReview
from inspinia.solutions.synthetic_reviews import case_choices
from inspinia.solutions.synthetic_reviews import create_synthetic_review
from inspinia.solutions.synthetic_reviews import private_report_payload
from inspinia.solutions.synthetic_reviews import require_prototype
from inspinia.solutions.synthetic_reviews import reveal_hint
from inspinia.solutions.synthetic_reviews import synthetic_packet

MAX_REQUEST_BYTES = 8192
HISTORY_LIMIT = 25


class ReviewPrototypeForm(forms.Form):
    case_id = forms.ChoiceField(label="Synthetic submission", widget=forms.HiddenInput)
    mode = forms.ChoiceField(
        label="Review mode",
        choices=list(MODES.items()),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["case_id"].choices = [(row["id"], row["label"]) for row in case_choices()]


class HintRevealForm(forms.Form):
    finding_id = forms.ChoiceField()
    level = forms.IntegerField(min_value=1, max_value=2)

    def __init__(self, *args, review, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["finding_id"].choices = [(key, key) for key in review.private_hints]


def _render(request, template, context, *, status=200):
    response = render(request, template, context, status=status)
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "same-origin"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def synthetic_review_workspace(request):
    require_prototype(request.user)
    if request.method == "POST" and len(request.body) > MAX_REQUEST_BYTES:
        return HttpResponseBadRequest("The prototype request is too large.")
    if request.method == "POST" and set(request.POST) - {"csrfmiddlewaretoken", "case_id", "mode", "idempotency_key"}:
        return HttpResponseBadRequest("The prototype accepts bundled synthetic case identifiers only.")
    choices = case_choices()
    selected = request.GET.get("case_id", choices[0]["id"])
    if selected not in {row["id"] for row in choices}:
        selected = choices[0]["id"]
    initial = {"case_id": selected, "mode": "coach"}
    form = ReviewPrototypeForm(request.POST if request.method == "POST" else None, initial=initial)
    status = 200
    if request.method == "POST":
        require_prototype(request.user, "add_syntheticreview")
        if form.is_valid():
            try:
                review, _created = create_synthetic_review(request.user, **form.cleaned_data)
            except (EvaluationDataError, ValidationError) as error:
                form.add_error(None, " ".join(error.messages) if isinstance(error, ValidationError) else str(error))
            else:
                return redirect("solutions:synthetic_review_detail", review_id=review.pk)
        status = 422
        selected = form.cleaned_data.get("case_id", selected)
    return _render(
        request,
        "solutions/synthetic-review-workspace.html",
        {
            "form": form,
            "packet": synthetic_packet(selected),
            "case_choices": choices,
            "selected_case": selected,
            "history": SyntheticReview.objects.only("pk", "case_id", "mode", "created_at")[:HISTORY_LIMIT],
            "can_create": request.user.has_perm("solutions.add_syntheticreview"),
        },
        status=status,
    )


@login_required
@never_cache
@require_GET
def synthetic_review_detail(request, review_id):
    require_prototype(request.user)
    review = get_object_or_404(SyntheticReview, pk=review_id)
    return _render(
        request,
        "solutions/synthetic-review-detail.html",
        {
            "review": review,
            "report": private_report_payload(review, request.user),
            "packet": review.packet,
            "mode_label": MODES[review.mode],
            "can_reveal": request.user.has_perm("solutions.add_synthetichintreveal"),
        },
    )


@login_required
@never_cache
@require_POST
def synthetic_review_hint(request, review_id):
    require_prototype(request.user)
    require_prototype(request.user, "add_synthetichintreveal")
    if len(request.body) > MAX_REQUEST_BYTES:
        return HttpResponseBadRequest("The hint request is too large.")
    review = get_object_or_404(SyntheticReview, pk=review_id)
    form = HintRevealForm(request.POST, review=review)
    if not form.is_valid():
        return HttpResponseBadRequest("Choose an available hint level.")
    try:
        reveal_hint(request.user, review, **form.cleaned_data)
    except ValidationError as error:
        return HttpResponseBadRequest(" ".join(error.messages))
    return redirect("solutions:synthetic_review_detail", review_id=review.pk)
