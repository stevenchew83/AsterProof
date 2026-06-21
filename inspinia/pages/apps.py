import contextlib

from django.apps import AppConfig


class PagesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inspinia.pages"

    def ready(self):
        with contextlib.suppress(ImportError):
            import inspinia.pages.signals  # noqa: F401
