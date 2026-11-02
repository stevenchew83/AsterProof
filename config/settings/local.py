# ruff: noqa: E501
from .base import *  # noqa: F403
from .base import BASE_DIR
from .base import DATABASES
from .base import INSTALLED_APPS
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = True
SYNTHETIC_REVIEW_PROTOTYPE_ENABLED = True
SOLUTION_DOCUMENT_WRITES_ENABLED = env.bool("SOLUTION_DOCUMENT_WRITES_ENABLED", default=True)
LEARNING_MODULE_ENABLED = env.bool("LEARNING_MODULE_ENABLED", default=True)
LEARNING_CONTRIBUTIONS_ENABLED = env.bool("LEARNING_CONTRIBUTIONS_ENABLED", default=True)
LEARNING_CONTENT_PACK_ROOT = env(
    "LEARNING_CONTENT_PACK_ROOT", default=str(BASE_DIR / ".learning-content-packs"),
)
LEARNING_PRIVATE_ASSET_ROOT = env(
    "LEARNING_PRIVATE_ASSET_ROOT", default=str(BASE_DIR / ".learning-private"),
)
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="WiUuInd2TDb4eVanjuiJ1NTpDBJJdSIB98xAt9NtthqoHOCl2jDIiYYjvNlMpzGg",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
ALLOWED_HOSTS = ["localhost", "0.0.0.0", "127.0.0.1"]  # noqa: S104

# DATABASES
# ------------------------------------------------------------------------------
DATABASES["default"] = env.db("DATABASE_URL", default="postgresql:///asterproof")
DATABASES["default"]["ATOMIC_REQUESTS"] = True

# CACHES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#caches
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    },
}

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend",
)

# django-extensions
# ------------------------------------------------------------------------------
# https://django-extensions.readthedocs.io/en/latest/installation_instructions.html#configuration
INSTALLED_APPS += ["django_extensions"]

# Your stuff...
# ------------------------------------------------------------------------------
