# Multi-stage: build the frontend, then package the whole product
# (UI + API + webhooks + stream) into one image that runs on one port.

# ---- frontend build stage ----
FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build \
    && find dist -name '*.map' -delete

# ---- runtime stage ----
FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2

LABEL maintainer="flowsmith" \
    version="1.6.0" \
    description="Flowsmith iPaaS — API + UI + Worker + Scheduler + Monitoring"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app
# Apply current Debian security updates (the base-image digest can lag the
# published glibc/zlib/apt fixes) and install the PostgreSQL client.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt \
    # Test-only tooling is not part of the runtime surface. Playwright ships a
    # bundled Node binary that carries high-severity CVEs and is never used by
    # the API/worker process.
    && pip uninstall -y playwright pytest pytest-asyncio pytest-cov pytest-xdist \
    && rm -rf /usr/local/lib/python3.12/site-packages/playwright

COPY backend/ ./backend
COPY docs/integration-platform/LIVE_CERTIFICATION_EVIDENCE.json ./docs/integration-platform/
#COPY USER_MANUAL.md ./USER_MANUAL.md
COPY --from=frontend /build/dist ./frontend/dist

RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/backend/data /app/backend/tmp /app/backend/data/objects \
    && chown -R appuser:appuser /app

USER appuser
WORKDIR /app/backend
EXPOSE 8000
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=10s --timeout=5s --start-period=45s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)" || exit 1

CMD ["python", "-m", "app.serve"]
