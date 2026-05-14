# ============================================================================
# HIRE — AI-Powered HR Intelligence Platform
# ============================================================================
# Stage 1: Build SvelteKit frontend -> static HTML/JS/CSS
# Stage 2: Python API + frontend static files in one container
# ============================================================================

# --- Stage 1: Build Frontend ---
FROM node:22-slim AS frontend-builder

WORKDIR /frontend

COPY frontend/package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build && rm -rf node_modules /root/.npm
# Output: /frontend/build/ (static HTML/JS/CSS)
# Only /frontend/build is COPIED into final stage, so node_modules in this
# builder layer is multi-stage-isolated (doesn't bloat final image).

# --- Stage 2: Python API + Frontend ---
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# System dependencies (gcc for builds, poppler+fonts for PDF rendering)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev curl postgresql-client \
    poppler-utils \
    tesseract-ocr tesseract-ocr-mya tesseract-ocr-eng \
    libicu-dev pkg-config \
    fonts-liberation fonts-dejavu-core fonts-noto-core fontconfig \
    && fc-cache -fv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

WORKDIR /app

# Python dependencies (cached layer)
# BuildKit cache mount = fast rebuilds without bloating image.
# --no-cache-dir + explicit ~/.cache/pip purge = no pip cache in final layer.
COPY backend/requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt
# BuildKit cache mount is NOT included in the final image layer,
# so no manual cleanup of /root/.cache/pip is needed.

# Application code
COPY backend/ ./backend/

# Instance config
COPY instance.yaml ./instance.yaml

# DB migrations (read at startup by backend.core.migrations)
COPY db/ ./db/

# Copy frontend build output
COPY --from=frontend-builder /frontend/build /app/static-frontend

# Data directories
RUN mkdir -p /data/cvs /data/screenshots /data/exports /data/uploads

# Entrypoint
COPY scripts/entrypoint.sh /app/scripts/entrypoint.sh
RUN chmod +x /app/scripts/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
