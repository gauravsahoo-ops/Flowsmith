# Multi-stage: build the frontend, then package the whole product
# (UI + API + webhooks + stream) into one image that runs on one port.

# ---- frontend build stage ----
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- runtime stage ----
FROM python:3.12-slim

LABEL maintainer="automation-platform" \
      version="0.3.1" \
      description="Automation platform — API + UI + Worker + Scheduler"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend
COPY --from=frontend /build/dist ./frontend/dist

RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/backend/data \
    && chown -R appuser:appuser /app

USER appuser
WORKDIR /app/backend
EXPOSE 8000
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)" || exit 1

CMD ["python", "-m", "app.serve"]
