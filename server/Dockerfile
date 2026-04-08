# ──────────────────────────────────────────────────────────────────────────────
# SRE Incident Response Simulator — Dockerfile
#
# Multi-stage build compatible with both:
#   - Standalone deployment (openenv-core from PyPI)
#   - In-repo development (local openenv sources)
#
# Build:
#   docker build -t sre-incident-sim:latest -f server/Dockerfile .
#
# Run:
#   docker run -p 8000:8000 -e SRE_TASK=memory-leak-easy sre-incident-sim:latest
#
# Task selection via environment variable:
#   SRE_TASK=memory-leak-easy        (default)
#   SRE_TASK=latency-spike-medium
#   SRE_TASK=cascading-failure-hard
# ──────────────────────────────────────────────────────────────────────────────

ARG BASE_IMAGE=ghcr.io/meta-pytorch/openenv-base:latest
FROM ${BASE_IMAGE} AS builder

WORKDIR /app

# git is required for any VCS-sourced dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

ARG BUILD_MODE=standalone
ARG ENV_NAME=sre-incident-sim

# Copy the entire project (build context = project root)
COPY . /app/env
WORKDIR /app/env

# Ensure uv is available
RUN if ! command -v uv >/dev/null 2>&1; then \
        curl -LsSf https://astral.sh/uv/install.sh | sh && \
        mv /root/.local/bin/uv /usr/local/bin/uv && \
        mv /root/.local/bin/uvx /usr/local/bin/uvx; \
    fi

# Install dependencies (use lockfile if present for reproducibility)
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -f uv.lock ]; then \
        uv sync --frozen --no-install-project --no-editable; \
    else \
        uv sync --no-install-project --no-editable; \
    fi

RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -f uv.lock ]; then \
        uv sync --frozen --no-editable; \
    else \
        uv sync --no-editable; \
    fi

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM ${BASE_IMAGE}

WORKDIR /app

# Copy virtualenv and source from builder
COPY --from=builder /app/env/.venv /app/.venv
COPY --from=builder /app/env        /app/env

# Use the virtualenv's binaries
ENV PATH="/app/.venv/bin:$PATH"

# Make project importable
ENV PYTHONPATH="/app/env:$PYTHONPATH"

# Default task (override with -e SRE_TASK=...)
ENV SRE_TASK=memory-leak-easy

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# Start the FastAPI server
CMD ["sh", "-c", "cd /app/env && uvicorn server.app:app --host 0.0.0.0 --port 8000"]
