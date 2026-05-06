from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any

from django.db.utils import OperationalError
from django.db.utils import ProgrammingError

from inspinia.pages.models import PageViewEvent

if TYPE_CHECKING:
    from uuid import UUID

    from django.http import HttpRequest

PATH_MAX_LENGTH = 255
LABEL_MAX_LENGTH = 160
CONTEST_NAME_MAX_LENGTH = 128


@dataclass(frozen=True)
class PageViewPayload:
    view_type: str
    label: str = ""
    object_uuid: UUID | None = None
    contest_name: str = ""
    contest_year: int | None = None
    metadata: dict[str, Any] | None = None


def _trim(value: object, *, max_length: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:max_length]


def record_page_view(
    request: HttpRequest,
    *,
    payload: PageViewPayload,
) -> PageViewEvent | None:
    if request.method != "GET":
        return None

    request_user = getattr(request, "user", None)
    user = request_user if getattr(request_user, "is_authenticated", False) else None
    try:
        return PageViewEvent.objects.create(
            user=user,
            view_type=payload.view_type,
            object_uuid=payload.object_uuid,
            label=_trim(payload.label, max_length=LABEL_MAX_LENGTH),
            contest_name=_trim(payload.contest_name, max_length=CONTEST_NAME_MAX_LENGTH),
            contest_year=payload.contest_year,
            path=_trim(request.get_full_path(), max_length=PATH_MAX_LENGTH),
            metadata=payload.metadata or {},
        )
    except (OperationalError, ProgrammingError):
        return None
