from __future__ import annotations

import uuid

from django.core.cache import caches
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError


class Command(BaseCommand):
    help = "Check that the configured default Django cache can write and read values."

    def handle(self, *args, **options) -> None:
        cache_backend = caches["default"]
        backend_path = f"{cache_backend.__class__.__module__}.{cache_backend.__class__.__qualname__}"
        key = f"cache-health:{uuid.uuid4().hex}"
        value = uuid.uuid4().hex
        read_value = None
        set_result = None
        try:
            set_result = cache_backend.set(key, value, timeout=30)
            read_value = cache_backend.get(key)
            cache_backend.delete(key)
        except Exception as exc:
            msg = f"Cache health check failed backend={backend_path}: {exc}"
            raise CommandError(msg) from exc

        if set_result is False:
            msg = f"Cache health check write failed backend={backend_path}"
            raise CommandError(msg)
        if read_value != value:
            msg = f"Cache health check readback mismatch backend={backend_path}"
            raise CommandError(msg)

        self.stdout.write(self.style.SUCCESS(f"Cache health check succeeded backend={backend_path}"))
