"""
With these settings, tests run faster.
"""

from .base import *  # noqa: F403
from .base import BASE_DIR
from .base import TEMPLATES
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="oGHZUA5EozouXCN9bBtbLwNLgJRqN1Jjp4ILrpSV0V41GEqTW6YOBcmehs9Nv0cM",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#test-runner
TEST_RUNNER = "django.test.runner.DiscoverRunner"

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# DEBUGGING FOR TEMPLATES
# ------------------------------------------------------------------------------
TEMPLATES[0]["OPTIONS"]["debug"] = True  # type: ignore[index]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "http://media.testserver/"
SOLUTION_DOCUMENT_WRITES_ENABLED = True
LEARNING_MODULE_ENABLED = False
LEARNING_CONTRIBUTIONS_ENABLED = True
LEARNING_PUBLICATION_ENABLED = True
LEARNING_PRIVATE_ASSET_ROOT = str(BASE_DIR / ".test-learning-assets")
LEARNING_AGREEMENT_VERSION = "synthetic-rights-retained-v1"
LEARNING_AGREEMENT_APPROVED = True
SYNTHETIC_REVIEW_PROTOTYPE_ENABLED = True
# Your stuff...
# ------------------------------------------------------------------------------
