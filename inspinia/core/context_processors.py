from django.db import OperationalError
from django.db import ProgrammingError

from inspinia.backoffice.models import BrandingConfig
from inspinia.backoffice.services import get_effective_feature_flags


def feature_flags(request):  # noqa: ANN001
    return {"feature_flags": get_effective_feature_flags()}


def branding(request):  # noqa: ANN001
    try:
        cfg = BrandingConfig.load()
    except (OperationalError, ProgrammingError):
        cfg = None
    return {"branding": cfg}
