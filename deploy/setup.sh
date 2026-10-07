#!/usr/bin/env bash
# Flowsmith production deploy script.
# Usage: ./deploy/setup.sh [--monitoring]
set -euo pipefail

# Secrets written below (.env.production) must never be world/group readable.
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

# Fresh clones/extracts may lose the executable bit.
chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true

# ── Helpers ───────────────────────────────────────────────────
red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }

# ── Pre-flight checks ────────────────────────────────────────
bold "Flowsmith Production Deploy"
echo ""

if ! command -v docker &>/dev/null; then
  red "ERROR: docker not found. Install Docker Desktop first."
  exit 1
fi

if ! docker compose version &>/dev/null 2>&1; then
  red "ERROR: docker compose not available."
  exit 1
fi

# ── Environment file ──────────────────────────────────────────
if [ ! -f .env.production ]; then
  red "ERROR: .env.production not found."
  echo "  Copy .env.production and fill in secrets:"
  echo "    cp .env.production .env.production.local"
  echo "    # edit .env.production.local"
  exit 1
fi

# Source .env.production for variable substitution
set -a
# shellcheck disable=SC1091
source .env.production
set +a

# Generate secrets if empty
generate_secret() {
  python3 -c "import secrets; print(secrets.token_urlsafe(48))" 2>/dev/null \
    || python -c "import secrets; print(secrets.token_urlsafe(48))"
}

if [ -z "${JWT_SECRET:-}" ]; then
  bold "Generating JWT_SECRET..."
  JWT_SECRET=$(generate_secret)
  echo "JWT_SECRET=$JWT_SECRET" >> .env.production
  green "JWT_SECRET generated and appended to .env.production"
fi

if [ -z "${CREDENTIALS_ENCRYPTION_KEY:-}" ]; then
  bold "Generating CREDENTIALS_ENCRYPTION_KEY..."
  CRED_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null \
    || python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || true)
  if [ -z "$CRED_KEY" ]; then
    red "WARNING: Could not generate CREDENTIALS_ENCRYPTION_KEY. Set it manually."
  else
    echo "CREDENTIALS_ENCRYPTION_KEY=$CRED_KEY" >> .env.production
    green "CREDENTIALS_ENCRYPTION_KEY generated and appended to .env.production"
  fi
fi

if [ -z "${POSTGRES_PASSWORD:-}" ]; then
  bold "Generating POSTGRES_PASSWORD..."
  PG_PASS=$(generate_secret)
  echo "POSTGRES_PASSWORD=$PG_PASS" >> .env.production
  green "POSTGRES_PASSWORD generated and appended to .env.production"
fi

if [ -z "${REDIS_PASSWORD:-}" ]; then
  bold "Generating REDIS_PASSWORD..."
  RED_PASS=$(generate_secret)
  echo "REDIS_PASSWORD=$RED_PASS" >> .env.production
  green "REDIS_PASSWORD generated and appended to .env.production"
fi

# ── Deploy ────────────────────────────────────────────────────
bold "Building and starting services..."

COMPOSE_PROFILES=""

# Check for --monitoring flag
if [[ "$*" == *"--monitoring"* ]]; then
  COMPOSE_PROFILES="monitoring"
  green "Monitoring profile enabled (Prometheus + Grafana)"
fi

if [ -n "$COMPOSE_PROFILES" ]; then
  COMPOSE_PROFILES="$COMPOSE_PROFILES" docker compose --env-file .env.production up -d --build
else
  docker compose --env-file .env.production up -d --build
fi

# ── Wait for health ───────────────────────────────────────────
bold "Waiting for services to become healthy..."
for i in {1..30}; do
  if docker inspect --format='{{.State.Health.Status}}' mat-app 2>/dev/null | grep -q healthy; then
    green "App is healthy!"
    break
  fi
  if [ "$i" -eq 30 ]; then
    red "WARNING: App did not become healthy in 30s. Check logs:"
    echo "  docker logs mat-app"
  fi
  sleep 1
done

# ── Summary ───────────────────────────────────────────────────
echo ""
bold "Deploy complete!"
echo ""
echo "  App:        http://localhost:${APP_PORT:-8000}"
echo "  Health:     http://localhost:${APP_PORT:-8000}/api/health"
echo "  Readiness:  http://localhost:${APP_PORT:-8000}/readyz"

if [[ "$*" == *"--monitoring"* ]]; then
  echo "  Prometheus: http://localhost:9090"
  echo "  Grafana:    http://localhost:3000 (user: admin)"
fi

echo ""
echo "  Logs:       docker logs -f mat-app"
echo "  Worker:     docker logs -f mat-worker"
echo "  Stop:       docker compose down"
echo ""
