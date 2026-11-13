# Build context = gateway/ (self-contained service, no shared library).
# Same digest as auth-svc's Dockerfile and the Makefile's PYTHON_IMAGE. Refresh it deliberately in all three:
#   docker pull python:3.12-slim  then update the ARG.
ARG PYTHON_IMAGE=python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

FROM ${PYTHON_IMAGE} AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PATH=/opt/venv/bin:$PATH
RUN python -m venv /opt/venv
WORKDIR /src
# NOT hash-locked yet (deviation D1 in the README): `make lock` was skipped by decision, so the dependencies resolve
# from pyproject.toml at build time. When requirements.lock and requirements-build.lock exist, replace this block
# with auth-svc's two `pip install --require-hashes --no-deps -r ...lock` steps.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH
RUN useradd --uid 10001 --system --no-create-home --shell /usr/sbin/nologin app
# Security patch for the pinned base image (Trivy: zlib1g CVE-2026-76844 / CVE-2026-85091, fixed in
# 1.3.1-1+deb13u1 but not yet in the published digest). Upgrades ONLY this package. This is the one step
# that is not reproducible from the digest alone; delete it once a newer python:3.12-slim digest is pinned.
RUN apt-get update \
 && apt-get install -y --no-install-recommends --only-upgrade zlib1g \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
# app/ is NOT copied again: it is installed in the venv from the wheel. The gateway has no database and no
# migrations; only the entrypoint is needed at runtime.
COPY scripts/entrypoint.sh ./entrypoint.sh
RUN chmod 0555 entrypoint.sh
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
ENTRYPOINT ["./entrypoint.sh"]
