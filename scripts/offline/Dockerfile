# Dependency-only image. Build with requirements/ as the entire build context.
# Execution uses the resulting immutable local image ID, never this mutable base tag.
FROM python:3.12.4-slim

LABEL io.asterproof.offline-dependencies="true"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /opt/offline-dependencies
COPY base.txt production.txt local.txt ./requirements/
RUN python -m pip install --requirement requirements/local.txt
RUN python -m pip check
RUN python -m pip freeze --all > /dependency-freeze.txt
