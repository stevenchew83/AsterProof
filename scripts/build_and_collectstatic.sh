#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# CI and release builds must select the already-provisioned, lock-installed
# environment explicitly. This avoids uv discovering the intentionally smaller
# pyproject/uv.lock environment and silently omitting production dependencies.
PYTHON_BIN="${ASTERPROOF_PYTHON:?Set ASTERPROOF_PYTHON to the release environment Python executable}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ASTERPROOF_PYTHON is not executable: $PYTHON_BIN" >&2
  exit 2
fi

npm ci
npm run build

# Use staticfiles settings so collectstatic does not require production secrets
# while still producing compressed, manifest-hashed production assets.
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.staticfiles}"
"$PYTHON_BIN" manage.py collectstatic --noinput

echo "collectstatic complete. Files are under STATIC_ROOT (repo root staticfiles/)."
