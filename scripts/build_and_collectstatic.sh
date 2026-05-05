#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

npm ci
npm run build

# Use staticfiles settings so collectstatic does not require production secrets
# while still producing compressed, manifest-hashed production assets.
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.staticfiles}"
uv run python manage.py collectstatic --noinput

echo "collectstatic complete. Files are under STATIC_ROOT (repo root staticfiles/)."
