"""Learning files never inherit the public media root or a public storage URL."""

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class LearningAssetStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(file_permissions_mode=0o600, directory_permissions_mode=0o700)

    @property
    def base_location(self):
        configured = getattr(settings, "LEARNING_PRIVATE_ASSET_ROOT", "")
        if not configured or not Path(configured).is_absolute():
            msg = "Configure an absolute private learning asset root before uploading."
            raise ImproperlyConfigured(msg)
        path = Path(configured)
        root = path.resolve()
        if path.is_symlink() or root == Path(root.anchor):
            msg = "Learning assets require a dedicated private directory."
            raise ImproperlyConfigured(msg)
        for name in ("MEDIA_ROOT", "STATIC_ROOT"):
            public = getattr(settings, name, "")
            if public and root.is_relative_to(Path(public).resolve()):
                msg = "Learning assets cannot be stored beneath a public file root."
                raise ImproperlyConfigured(msg)
        return str(root)

    @property
    def location(self):
        return self.base_location

    def url(self, name):
        msg = "Learning assets are delivered only by an authorised application view."
        raise NotImplementedError(msg)
