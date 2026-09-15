# syntax=docker/dockerfile:1.6

############################
# Builder stage
############################
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=2.2.1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

RUN poetry config virtualenvs.in-project true

# Copy dependency manifests first so this layer caches on dependency changes only
COPY pyproject.toml poetry.lock ./

# Install third-party runtime dependencies into /app/.venv
RUN poetry install --only main --no-root --no-interaction --no-ansi

# Copy source and install only the root application package.
# README.md is required because pyproject.toml declares it as the package readme.
COPY README.md ./
COPY src ./src
RUN poetry install --only-root --no-interaction --no-ansi

############################
# Runtime stage
############################
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# The venv's root-package installation references /app/src, so both must land
# at the same absolute paths as in the builder stage.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Healthcheck using Python stdlib (no curl required)
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD python -c "import urllib.request; import sys; \
url='http://127.0.0.1:8000/health'; \
sys.exit(0) if urllib.request.urlopen(url, timeout=2).status==200 else sys.exit(1)"

USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
