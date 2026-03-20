from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods
from django.views.generic import DetailView
from django.views.generic import RedirectView
from django.views.generic import UpdateView

from inspinia.users.models import User
from inspinia.users.roles import user_has_admin_role


class UserDetailView(LoginRequiredMixin, DetailView):
    model = User
    slug_field = "id"
    slug_url_kwarg = "id"


user_detail_view = UserDetailView.as_view()


class UserUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = User
    fields = ["name"]
    success_message = _("Information successfully updated")

    def get_success_url(self) -> str:
        assert self.request.user.is_authenticated  # type guard
        return self.request.user.get_absolute_url()

    def get_object(self, queryset: QuerySet | None=None) -> User:
        assert self.request.user.is_authenticated  # type guard
        return self.request.user


user_update_view = UserUpdateView.as_view()


class UserRedirectView(LoginRequiredMixin, RedirectView):
    permanent = False

    def get_redirect_url(self) -> str:
        return reverse("users:detail", kwargs={"pk": self.request.user.pk})


user_redirect_view = UserRedirectView.as_view()


@login_required
@require_http_methods(["GET", "POST"])
def manage_user_roles_view(request):
    """Assign application roles (admin / moderator / trainer / normal). Admins only."""
    if not user_has_admin_role(request.user):
        raise PermissionDenied

    allowed_roles = {choice[0] for choice in User.Role.choices}

    if request.method == "POST":
        raw_id = request.POST.get("user_id")
        new_role = request.POST.get("role")
        try:
            target = User.objects.get(pk=int(raw_id)) if raw_id else None
        except (User.DoesNotExist, ValueError, TypeError):
            target = None

        if target is None or new_role not in allowed_roles:
            messages.error(request, _("Invalid user or role."))
        else:
            target.role = new_role
            target.save(update_fields=["role"])
            messages.success(
                request,
                _("Updated role for %(email)s to %(role)s.")
                % {"email": target.email, "role": target.get_role_display()},
            )
        return redirect("users:manage_roles")

    users_qs = User.objects.order_by("email")
    return render(
        request,
        "users/manage_roles.html",
        {
            "users": users_qs,
            "role_choices": User.Role.choices,
        },
    )
