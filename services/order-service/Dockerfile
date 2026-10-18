# Build context: repository root (see compose.yaml), so the root .dockerignore applies.
FROM python:3.13.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_PORT=8000 \
    GRACEFUL_SHUTDOWN_SECONDS=20

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --no-create-home app

COPY services/order-service/requirements.txt .
RUN pip install -r requirements.txt

COPY services/order-service/alembic.ini .
COPY services/order-service/alembic ./alembic
COPY services/order-service/app ./app

USER app

EXPOSE 8000
STOPSIGNAL SIGTERM

# Migrations run before the server starts; `exec` makes Uvicorn PID 1 so it receives SIGTERM
# directly and shuts down gracefully (finishes in-flight requests, runs the lifespan shutdown).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT} --timeout-graceful-shutdown ${GRACEFUL_SHUTDOWN_SECONDS}"]
