"""Navigation permissions without querying learner or document data."""

from inspinia.learning.permissions import can_contribute
from inspinia.learning.permissions import is_publisher
from inspinia.learning.permissions import module_enabled


def learning_navigation(request):
    return {
        "learning_enabled": module_enabled(),
        "learning_can_contribute": can_contribute(request.user),
        "learning_is_publisher": is_publisher(request.user),
    }
