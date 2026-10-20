# Build context: repository root (see compose.yaml), so the root .dockerignore applies.
# Minor-version tag (not a patch pin) so rebuilds pick up the latest Python patch and Debian base.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_PORT=8000 \
    GRACEFUL_SHUTDOWN_SECONDS=20

WORKDIR /app

# Apply pending Debian security fixes and upgrade pip, which the base image may ship outdated.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip

RUN groupadd --system app && useradd --system --gid app --no-create-home app

COPY services/payment-service/requirements.txt .
RUN pip install -r requirements.txt

COPY services/payment-service/alembic.ini .
COPY services/payment-service/alembic ./alembic
COPY services/payment-service/app ./app

USER app

EXPOSE 8000
STOPSIGNAL SIGTERM

# Migrations run before the server starts; `exec` makes Uvicorn PID 1 so it receives SIGTERM
# directly and shuts down gracefully (finishes in-flight requests, runs the lifespan shutdown).
# `opentelemetry-instrument` wraps only Uvicorn (not Alembic); it is configured via OTEL_* env vars.
CMD ["sh", "-c", "alembic upgrade head && exec opentelemetry-instrument uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT} --timeout-graceful-shutdown ${GRACEFUL_SHUTDOWN_SECONDS}"]
