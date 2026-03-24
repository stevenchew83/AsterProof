#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

npm install
npm run build

# Use test settings so collectstatic does not require production DB env.
# Output matches STATICFILES_DIRS → STATIC_ROOT the same as local/production for static files.
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.test}"
uv run python manage.py collectstatic --noinput

echo "collectstatic complete. Files are under STATIC_ROOT (repo root staticfiles/)."
