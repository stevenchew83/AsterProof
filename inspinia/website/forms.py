from django import forms

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
