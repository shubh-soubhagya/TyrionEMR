# Build context = auth-svc/ (the service is self-contained: no shared library)
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
# The whole package is copied here so `pip wheel` can build it (copying only pyproject.toml would
# produce an empty wheel).
COPY pyproject.toml ./
COPY app ./app
RUN pip wheel --wheel-dir /wheels .

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --system --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY app ./app
COPY scripts/entrypoint.sh ./entrypoint.sh
RUN chmod 0555 entrypoint.sh
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
ENTRYPOINT ["./entrypoint.sh"]
