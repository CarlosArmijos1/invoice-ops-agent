# syntax=docker/dockerfile:1.7

# ---------- Backend dependencies ----------
FROM python:3.12-slim AS backend-deps
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app/backend
# Install third-party deps first so this layer is cached across code changes.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------- Runtime ----------
FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOG_JSON=true
RUN useradd --create-home --uid 1000 app
WORKDIR /app/backend
COPY --from=backend-deps /opt/venv /opt/venv
COPY --from=backend-deps /app/backend /app/backend
# Synthetic dataset (demo bootstrap) and recorded LLM responses (replay/hybrid modes).
COPY data/synthetic /app/data/synthetic
COPY evals/cassettes /app/evals/cassettes
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status == 200 else 1)"
# Migrations run on start-up: simple and safe for a single instance. With several
# replicas this would move to a one-off release job (e.g. Render pre-deploy command).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn opsagent.api.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=*"]
