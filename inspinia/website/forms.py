from django import forms


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
