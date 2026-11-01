from django.apps import AppConfig


class SolutionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inspinia.solutions"

    def ready(self):
        from . import evaluation_privacy  # noqa: F401
