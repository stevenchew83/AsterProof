from __future__ import annotations

import typing
from email.mime.image import MIMEImage

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

if typing.TYPE_CHECKING:
    from allauth.socialaccount.models import SocialLogin
    from django.http import HttpRequest

    from inspinia.users.models import User


def _apply_signup_auto_approval(user: User) -> None:
    from inspinia.users.models import UserAccessSettings

    if UserAccessSettings.get_solo().auto_approve_new_users:
        user.is_approved = True


class AccountAdapter(DefaultAccountAdapter):
    def render_mail(self, template_prefix, email, context, headers=None):
        message = super().render_mail(template_prefix, email, context, headers=headers)
        if isinstance(message, EmailMultiAlternatives) and not message.alternatives:
            # Give every account notification the same HTML shell, retaining its
            # original plain text, security details, recipients and headers.
            html = render_to_string(
                "account/email/fallback_message.html",
                {
                    **context,
                    "email_heading": message.subject.removeprefix(settings.ACCOUNT_EMAIL_SUBJECT_PREFIX),
                    "email_body": message.body,
                },
            )
            message.attach_alternative(html, "text/html")
        if isinstance(message, EmailMultiAlternatives) and any(
            'src="cid:asterproof-logo"' in body for body, mimetype in message.alternatives if mimetype == "text/html"
        ):
            logo_path = settings.APPS_DIR / "static/images/asterproof-logo-email.png"
            logo = MIMEImage(logo_path.read_bytes(), _subtype="png")
            logo.add_header("Content-ID", "<asterproof-logo>")
            logo.add_header("Content-Disposition", "inline", filename="asterproof-logo.png")
            message.mixed_subtype = "related"
            message.attach(logo)
        return message

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def save_user(self, request: HttpRequest, user: User, form, commit=True) -> User:  # noqa: FBT002
        _apply_signup_auto_approval(user)
        return super().save_user(request, user, form, commit=commit)

    def post_login(  # noqa: PLR0913
        self,
        request: HttpRequest,
        user: User,
        *,
        email_verification,
        signal_kwargs,
        email,
        signup,
        redirect_url,
    ):
        if not signup:
            redirect_url = reverse("pages:user_activity_dashboard")
        return super().post_login(
            request,
            user,
            email_verification=email_verification,
            signal_kwargs=signal_kwargs,
            email=email,
            signup=signup,
            redirect_url=redirect_url,
        )


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(
        self,
        request: HttpRequest,
        sociallogin: SocialLogin,
    ) -> bool:
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def populate_user(
        self,
        request: HttpRequest,
        sociallogin: SocialLogin,
        data: dict[str, typing.Any],
    ) -> User:
        """
        Populates user information from social provider info.

        See: https://docs.allauth.org/en/latest/socialaccount/advanced.html#creating-and-populating-user-instances
        """
        user = super().populate_user(request, sociallogin, data)
        if not user.name:
            if name := data.get("name"):
                user.name = name
            elif first_name := data.get("first_name"):
                user.name = first_name
                if last_name := data.get("last_name"):
                    user.name += f" {last_name}"
        return user

    def save_user(self, request: HttpRequest, sociallogin: SocialLogin, form=None) -> User:
        _apply_signup_auto_approval(sociallogin.user)
        return super().save_user(request, sociallogin, form=form)
