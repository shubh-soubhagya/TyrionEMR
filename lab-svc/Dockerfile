# Build context = lab-svc/ (self-contained service, no shared library).
# One digest for both stages. Refresh it deliberately:  docker pull python:3.12-slim  then update the ARG.
ARG PYTHON_IMAGE=python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

FROM ${PYTHON_IMAGE} AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PATH=/opt/venv/bin:$PATH
RUN python -m venv /opt/venv
WORKDIR /src
# 1. Build tooling and runtime dependencies come ONLY from hash-locked files (--require-hashes rejects
#    any package whose hash is not in the lock, so a tampered or substituted package fails the build).
COPY requirements-build.lock requirements.lock ./
RUN pip install --require-hashes --no-deps -r requirements-build.lock \
 && pip install --require-hashes --no-deps -r requirements.lock
# 2. Our own package, built offline against the pinned setuptools, installed into the venv.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-build-isolation --no-deps .

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
# app/ is NOT copied again: it is installed in the venv from the wheel. Only what is not part of the
# package is needed at runtime: alembic.ini + migrations (alembic and /ready's head-revision check read
# them from the working directory) and the entrypoint.
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY scripts/entrypoint.sh ./entrypoint.sh
RUN chmod 0555 entrypoint.sh
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
ENTRYPOINT ["./entrypoint.sh"]
