from django import forms
from django.utils import timezone

from .models import NewsletterAutomation
from .models import NewsletterCampaign

MAX_BODY_LENGTH = 30000


class NewsletterForm(forms.Form):
    email = forms.EmailField(
        max_length=254,
        label="Email address",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "Your email address"}),
    )
    consent = forms.BooleanField(label="Email me new lectures and AsterProof updates.")
    company = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_email(self):
        return self.cleaned_data["email"].strip().casefold()


class NewsletterCampaignForm(forms.ModelForm):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    class Meta:
        model = NewsletterCampaign
        fields = ["subject", "preheader", "body_markdown"]
        widgets = {
            "subject": forms.TextInput(attrs={"class": "form-control", "placeholder": "A new idea to explore"}),
            "preheader": forms.TextInput(attrs={"class": "form-control", "placeholder": "A short inbox preview"}),
            "body_markdown": forms.Textarea(attrs={"class": "form-control newsletter-source", "rows": 10}),
        }
        labels = {"body_markdown": "Message", "preheader": "Inbox preview"}
        help_texts = {
            "body_markdown": (
                "Use Markdown for headings, lists and links. The logo and unsubscribe footer are added for you."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = self.instance.version
        self.fields["body_markdown"].max_length = MAX_BODY_LENGTH
        self.fields["body_markdown"].widget.attrs["maxlength"] = MAX_BODY_LENGTH

    def clean_subject(self):
        subject = self.cleaned_data["subject"].strip()
        if "\n" in subject or "\r" in subject:
            message = "Use a single line for the subject."
            raise forms.ValidationError(message)
        return subject

    def clean_body_markdown(self):
        body = self.cleaned_data["body_markdown"].strip()
        if len(body) > MAX_BODY_LENGTH:
            message = "Keep the message within 30,000 characters."
            raise forms.ValidationError(message)
        return body


class NewsletterSendForm(forms.Form):
    version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    confirm = forms.BooleanField(label="I have reviewed this version and its test email.")


class NewsletterScheduleForm(NewsletterSendForm):
    scheduled_at = forms.DateTimeField(
        label="Send at (Malaysia time)",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control form-control-sm"}),
    )

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("auto_id", "schedule_%s")
        super().__init__(*args, **kwargs)

    def clean_scheduled_at(self):
        when = self.cleaned_data["scheduled_at"]
        if when <= timezone.now():
            msg = "Choose a future date and time."
            raise forms.ValidationError(msg)
        return when


class NewsletterAutomationForm(forms.ModelForm):
    confirm = forms.BooleanField(
        required=False,
        label="I approve automatic lecture emails to confirmed subscribers.",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    class Meta:
        model = NewsletterAutomation
        fields = ["lecture_enabled", "lecture_template", "digest_time"]
        labels = {
            "lecture_enabled": "Enable lecture digests", "lecture_template": "Tested introduction draft",
            "digest_time": "Daily time (MYT)",
        }
        widgets = {
            "lecture_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "lecture_template": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "digest_time": forms.TimeInput(attrs={"type": "time", "class": "form-control form-control-sm"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lecture_template"].queryset = NewsletterCampaign.objects.filter(
            status=NewsletterCampaign.Status.DRAFT, started_at__isnull=True,
        )
        self.fields["lecture_template"].required = False

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("lecture_enabled") and (not cleaned.get("confirm") or not cleaned.get("lecture_template")):
            msg = "Choose a tested introduction and confirm automatic lecture emails."
            raise forms.ValidationError(msg)
        return cleaned


class NewsletterBounceUploadForm(forms.Form):
    report = forms.FileField(
        label="Gmail delivery-failure email (.eml)",
        widget=forms.ClearableFileInput(attrs={"accept": ".eml", "class": "form-control form-control-sm"}),
    )

    def clean_report(self):
        report = self.cleaned_data["report"]
        if report.size > 1024 * 1024 or not report.name.casefold().endswith(".eml"):
            msg = "Choose a saved .eml delivery report no larger than 1 MB."
            raise forms.ValidationError(msg)
        return report


class NewsletterBounceApplyForm(forms.Form):
    token = forms.CharField(max_length=4096, widget=forms.HiddenInput)
    confirm = forms.BooleanField(label="I verified this report came from my Gmail delivery-failure notice.")


class NewsletterHoldClearForm(forms.Form):
    reason = forms.CharField(max_length=180, widget=forms.TextInput(attrs={
        "class": "form-control form-control-sm", "placeholder": "Why this address can receive newsletters again",
    }))
    confirm = forms.BooleanField(label="I reviewed the bounce and want to restore newsletter sending.")
