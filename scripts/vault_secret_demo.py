"""D10 Vault Agent file-injection demo.

Runs an isolated Vault dev server + Vault Agent, writes fresh app secrets to
Vault, renders them into files, and starts an isolated Flowsmith app that reads
only the rendered `*_FILE` inputs. The demo uses a separate `vault_demo`
database and Redis logical database 10, then removes everything.

This is an integration demonstration. A production Vault deployment still needs
persistent storage, TLS, and non-root auth (AppRole/Kubernetes), which is an
operations task.

Run with Docker Desktop and the `mat-*` services available:
    .venv\\Scripts\\python.exe scripts\\vault_secret_demo.py
"""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "flowsmith-app:latest"
VAULT_IMAGE = "hashicorp/vault:1.18"
NETWORK = "flowsmith_backend"
VAULT_NAME = "flowsmith-vault"
AGENT_NAME = "flowsmith-vault-agent"
APP_NAME = "flowsmith-vault-app"
VOLUME = "flowsmith_vault_secrets"
ROOT_TOKEN = "flowsmith-demo-root"
DEMO_DB = "vault_demo"
APP_PORT = 18081
VAULT_PORT = 8201
SECRET_PATH = "secret/data/flowsmith"


def run(cmd: list[str], *, check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(cmd[:4])}\n"
            f"{result.stdout[-1500:]}\n{result.stderr[-1500:]}"
        )
    return result


def docker(*args: str, check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess:
    return run(["docker", *args], check=check, timeout=timeout)


def docker_env(name: str, key: str) -> str:
    result = docker("exec", name, "printenv", key, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def wait_container_healthy(name: str, timeout: float = 120.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = docker(
            "inspect",
            "-f",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
            name,
            check=False,
        ).stdout.strip()
        if status in ("healthy", "running"):
            return True
        time.sleep(1.0)
    return False


def wait_http(url: str, timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=5.0)
            if response.status_code < 500:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1.0)
    return False


def cleanup() -> None:
    docker("rm", "-f", APP_NAME, AGENT_NAME, VAULT_NAME, check=False)
    docker("volume", "rm", "-f", VOLUME, check=False)
    result = docker(
        "exec",
        "mat-postgres",
        "psql",
        "-U",
        "automate",
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        f"DROP DATABASE IF EXISTS {DEMO_DB};",
        check=False,
    )
    if result.returncode != 0:
        print("demo_db_cleanup_warning", result.stderr.strip()[:200])


def main() -> int:
    if docker("info", check=False).returncode != 0:
        print("docker_not_running")
        return 1
    if docker("image", "inspect", IMAGE, check=False).returncode != 0:
        print(f"missing_image={IMAGE}")
        return 1
    if docker("image", "inspect", VAULT_IMAGE, check=False).returncode != 0:
        print(f"missing_image={VAULT_IMAGE}; pull it first")
        return 1
    if docker("network", "inspect", NETWORK, check=False).returncode != 0:
        print(f"missing_network={NETWORK}")
        return 1
    for service in ("mat-postgres", "mat-redis"):
        state = docker("inspect", "-f", "{{.State.Running}}", service, check=False)
        if state.stdout.strip() != "true":
            docker("start", service, check=False)
        if not wait_container_healthy(service):
            print(f"service_not_healthy={service}")
            return 1

    cleanup()
    tmpdir = Path(tempfile.mkdtemp(prefix="vault_demo_"))
    templates = tmpdir / "templates"
    templates.mkdir(parents=True, exist_ok=True)

    jwt_secret = secrets.token_hex(32)
    encryption_key = Fernet.generate_key().decode()
    postgres_password = docker_env("mat-postgres", "POSTGRES_PASSWORD") or "automate"
    database_url = (
        f"postgresql://automate:{postgres_password}@mat-postgres:5432/{DEMO_DB}"
    )
    redis_url = "redis://mat-redis:6379/10"
    ping = docker("exec", "mat-redis", "redis-cli", "ping", check=False)
    if ping.stdout.strip() != "PONG":
        # Fall back to the main app URL with a different logical database.
        main_redis = docker_env("mat-app", "REDIS_URL")
        if main_redis:
            base, _, _ = main_redis.rpartition("/")
            redis_url = f"{base}/10"
        else:
            redis_url = ""

    def add_template(name: str, expression: str) -> None:
        (templates / f"{name}.tmpl").write_text(expression, encoding="utf-8")

    add_template("jwt_secret", '{{- with secret "' + SECRET_PATH + '" -}}{{ .Data.data.jwt_secret }}{{- end -}}')
    add_template(
        "credentials_encryption_key",
        '{{- with secret "' + SECRET_PATH + '" -}}{{ .Data.data.credentials_encryption_key }}{{- end -}}',
    )
    add_template(
        "database_url",
        '{{- with secret "' + SECRET_PATH + '" -}}{{ .Data.data.database_url }}{{- end -}}',
    )
    add_template(
        "redis_url",
        '{{- with secret "' + SECRET_PATH + '" -}}{{ .Data.data.redis_url }}{{- end -}}',
    )

    template_blocks = "\n".join(
        f'''template {{
  source      = "/vault/templates/{name}.tmpl"
  destination = "/vault/secrets/{name}"
  perms       = "0444"
}}'''
        for name in (
            "jwt_secret",
            "credentials_encryption_key",
            "database_url",
            "redis_url",
        )
    )
    (tmpdir / "token").write_text(ROOT_TOKEN, encoding="utf-8")
    (tmpdir / "agent.hcl").write_text(
        f'''vault {{
  address = "http://{VAULT_NAME}:8200"
}}

auto_auth {{
  method "token_file" {{
    config {{
      token_file_path = "/vault/token"
    }}
  }}
}}

{template_blocks}
''',
        encoding="utf-8",
    )

    try:
        docker(
            "run",
            "-d",
            "--name",
            VAULT_NAME,
            "--network",
            NETWORK,
            "-p",
            f"127.0.0.1:{VAULT_PORT}:8200",
            "-e",
            f"VAULT_DEV_ROOT_TOKEN_ID={ROOT_TOKEN}",
            "-e",
            "VAULT_DEV_LISTEN_ADDRESS=0.0.0.0:8200",
            VAULT_IMAGE,
            "server",
            "-dev",
            f"-dev-root-token-id={ROOT_TOKEN}",
        )
        if not wait_http(f"http://127.0.0.1:{VAULT_PORT}/v1/sys/health", 90):
            print("vault_not_healthy")
            return 1
        print("vault=healthy")

        payload = {
            "data": {
                "jwt_secret": jwt_secret,
                "credentials_encryption_key": encryption_key,
                "database_url": database_url,
                "redis_url": redis_url,
            }
        }
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"http://127.0.0.1:{VAULT_PORT}/v1/{SECRET_PATH}",
                headers={"X-Vault-Token": ROOT_TOKEN},
                json=payload,
            )
            if response.status_code >= 400:
                print("vault_write_failed", response.status_code, response.text[:300])
                return 1
        print("vault_secrets=written")

        docker(
            "run",
            "-d",
            "--name",
            AGENT_NAME,
            "--network",
            NETWORK,
            "--user",
            "root",
            "--entrypoint",
            "vault",
            "-v",
            f"{tmpdir}:/vault",
            "-v",
            f"{VOLUME}:/vault/secrets",
            VAULT_IMAGE,
            "agent",
            "-config=/vault/agent.hcl",
        )
        files_ready = False
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            check = docker(
                "exec",
                AGENT_NAME,
                "sh",
                "-c",
                "for f in jwt_secret credentials_encryption_key database_url redis_url; "
                "do test -s /vault/secrets/$f || exit 1; done",
                check=False,
            )
            if check.returncode == 0:
                files_ready = True
                break
            time.sleep(1)
        if not files_ready:
            print("agent_files_not_rendered")
            logs = docker("logs", "--tail", "40", AGENT_NAME, check=False)
            print(logs.stdout[-3000:])
            print(logs.stderr[-3000:])
            return 1
        print("agent_files=ok")

        create_db = docker(
            "exec",
            "mat-postgres",
            "psql",
            "-U",
            "automate",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            f"DROP DATABASE IF EXISTS {DEMO_DB};",
            "-c",
            f"CREATE DATABASE {DEMO_DB};",
            check=False,
        )
        if create_db.returncode != 0:
            print("demo_db_create_failed", create_db.stderr[:300])
            return 1
        print("demo_db=created")

        mount = f"{VOLUME}:/vault/secrets:ro"
        migrate = docker(
            "run",
            "--rm",
            "--network",
            NETWORK,
            "-v",
            mount,
            "-e",
            "APP_ENV=development",
            "-e",
            "DATABASE_URL_FILE=/vault/secrets/database_url",
            "-e",
            "REDIS_URL_FILE=/vault/secrets/redis_url",
            "-e",
            "JWT_SECRET_FILE=/vault/secrets/jwt_secret",
            "-e",
            "CREDENTIALS_ENCRYPTION_KEY_FILE=/vault/secrets/credentials_encryption_key",
            "--entrypoint",
            "python",
            IMAGE,
            "-m",
            "app.scripts.migrate",
            check=False,
            timeout=600,
        )
        if migrate.returncode != 0:
            print("migration_failed")
            print(migrate.stdout[-1500:])
            print(migrate.stderr[-1500:])
            return 1
        print("migrations=ok")

        app = docker(
            "run",
            "-d",
            "--name",
            APP_NAME,
            "--network",
            NETWORK,
            "-p",
            f"127.0.0.1:{APP_PORT}:{APP_PORT}",
            "-v",
            mount,
            "-e",
            "APP_ENV=development",
            "-e",
            f"PORT={APP_PORT}",
            "-e",
            f"PUBLIC_URL=http://127.0.0.1:{APP_PORT}",
            "-e",
            "SERVE_FRONTEND=false",
            "-e",
            "QUEUE_BACKEND=db",
            "-e",
            "QUEUE_EMBEDDED_CONSUMER=false",
            "-e",
            "OUTBOX_RELAY_ENABLED=false",
            "-e",
            "DATABASE_URL_FILE=/vault/secrets/database_url",
            "-e",
            "REDIS_URL_FILE=/vault/secrets/redis_url",
            "-e",
            "JWT_SECRET_FILE=/vault/secrets/jwt_secret",
            "-e",
            "CREDENTIALS_ENCRYPTION_KEY_FILE=/vault/secrets/credentials_encryption_key",
            "--entrypoint",
            "python",
            IMAGE,
            "-m",
            "app.serve",
            check=False,
        )
        if app.returncode != 0:
            print("app_start_failed")
            print(app.stderr[-1000:])
            return 1
        if not wait_http(f"http://127.0.0.1:{APP_PORT}/api/health", 120):
            print("app_health_failed")
            docker("logs", "--tail", "40", APP_NAME, check=False)
            return 1
        ready = httpx.get(f"http://127.0.0.1:{APP_PORT}/api/readyz", timeout=10).json()
        print("app_health=ok")
        print("app_ready=" + str((ready.get("data") or {}).get("status")))
        print("checks=" + json.dumps((ready.get("data") or {}).get("checks") or {}, sort_keys=True))

        # Prove the rendered encryption key works through the real credential API.
        stamp = f"{int(time.time())}{secrets.token_hex(3)}"
        email = f"vault.demo.{stamp}@example.com"
        password = "VaultDemoP@ss1"
        client = httpx.Client(base_url=f"http://127.0.0.1:{APP_PORT}", timeout=30)
        try:
            client.post("/api/auth/register", json={"email": email, "password": password})
            login = client.post(
                "/api/auth/login", json={"email": email, "password": password}
            )
            token = (login.json().get("data") or {}).get("token") if login.status_code == 200 else ""
            if not token:
                print("credential_roundtrip=login_failed")
                return 1
            headers = {"Authorization": f"Bearer {token}"}
            created = client.post(
                "/api/credentials",
                headers=headers,
                json={
                    "name": "Vault Demo Credential",
                    "type": "bearer_auth",
                    "data": {"token": "vault-demo-token"},
                },
            )
            if created.status_code != 201:
                print("credential_roundtrip=create_failed", created.status_code)
                return 1
            credential_id = (created.json().get("data") or {}).get("id")
            deleted = client.delete(
                f"/api/credentials/{credential_id}", headers=headers
            )
            if deleted.status_code not in (200, 204):
                print("credential_roundtrip=delete_failed", deleted.status_code)
                return 1
            print("credential_roundtrip=ok")
        finally:
            client.close()

        print("vault_agent_demo=PASS")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
