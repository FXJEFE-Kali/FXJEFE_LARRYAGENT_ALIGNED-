# syntax=docker/dockerfile:1.7
# ============================================================================
# Agent Larry — multi-stage container image
# ----------------------------------------------------------------------------
# Stage 1 (builder): install build deps + pip packages
# Stage 2 (runtime): slim image with only runtime deps — ~40% smaller
#
# Build:    docker build -t larry-agent:latest .
# Multi:    docker buildx build --platform linux/amd64,linux/arm64 -t larry-agent:latest .
# Run:      docker compose up -d
# ============================================================================

# ── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /build/requirements.txt
RUN pip install --prefix=/install -r /build/requirements.txt \
    && pip install --prefix=/install playwright

# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LARRY_HOME=/app \
    OLLAMA_URL=http://ollama:11434/api/chat \
    OLLAMA_HOST=http://ollama:11434 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TOKENIZERS_PARALLELISM=false \
    ANONYMIZED_TELEMETRY=False \
    CHROMA_TELEMETRY=False \
    DO_NOT_TRACK=1 \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

# Runtime system deps only (no build-essential, no git)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        jq \
        sqlite3 \
        ca-certificates \
        tini \
        # Playwright / headless Chromium runtime libs
        libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
        libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 \
        libxshmfence1 libxtst6 fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built Python packages from builder
COPY --from=builder /install /usr/local

# Install Playwright browsers (needs the pip package already present)
RUN playwright install --with-deps chromium

# Application source (respects .dockerignore)
COPY . /app

# Writable runtime dirs — volume mount-points in docker-compose.yml
RUN mkdir -p \
        /app/data \
        /app/logs \
        /app/exports \
        /app/chroma_db \
        /app/sandbox \
        /app/.file_backups \
    && chmod -R a+rw /app/data /app/logs /app/exports /app/chroma_db /app/sandbox

EXPOSE 3777

# Healthcheck — validates Python + core imports work
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "from larry_paths import BASE_DIR, __version__; print(f'ok v{__version__}')" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "python"]
CMD ["/app/agent_v2.py"]
