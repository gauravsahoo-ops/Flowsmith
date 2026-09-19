# FlowSmith — Third-Party Dependency & License Governance

This document provides a formal inventory and license governance audit for all direct dependencies used within the FlowSmith platform (Backend and Frontend), establishing legal certainty and compliance for commercial distribution.

## License Summary Matrix

| Ecosystem | Direct Packages | Permissive (MIT / Apache-2.0 / BSD / ISC) | Weak Copyleft (LGPL w/ exception) | Strong Copyleft (GPL/AGPL) | High Risk |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Backend (Python 3.12)** | 28 | 27 | 1 (`psycopg2-binary`) | 0 | **0 (None)** |
| **Frontend (React 19)** | 16 | 16 | 0 | 0 | **0 (None)** |

---

## 1. Backend Dependencies (`backend/requirements.txt`)

| Package | Version | License | Source / Repository | Purpose | Distribution / Commercial Status | Copyleft Risk |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `fastapi` | `0.141.1` | MIT | [GitHub](https://github.com/fastapi/fastapi) | Core async REST API framework | Fully Permissive | None |
| `uvicorn` | `0.52.4` | BSD-3-Clause | [GitHub](https://github.com/encode/uvicorn) | ASGI HTTP & WebSocket server | Fully Permissive | None |
| `pydantic` | `2.13.4` | MIT | [GitHub](https://github.com/pydantic/pydantic) | Data validation & schemas | Fully Permissive | None |
| `pydantic-settings` | `2.15.0` | MIT | [GitHub](https://github.com/pydantic/pydantic-settings) | Environment configuration loader | Fully Permissive | None |
| `httpx` | `0.28.1` | BSD-3-Clause | [GitHub](https://github.com/encode/httpx) | Async HTTP client for HTTP nodes & OAuth | Fully Permissive | None |
| `sqlalchemy` | `2.0.52` | MIT | [GitHub](https://github.com/sqlalchemy/sqlalchemy) | Database ORM & Connection pool | Fully Permissive | None |
| `alembic` | `1.20.0` | MIT | [GitHub](https://github.com/sqlalchemy/alembic) | Database migration engine | Fully Permissive | None |
| `cryptography` | `50.0.0` | Apache-2.0 / BSD-3 | [GitHub](https://github.com/pyca/cryptography) | AES-256-GCM credential encryption | Fully Permissive | None |
| `PyJWT` | `2.13.0` | MIT | [GitHub](https://github.com/jpadilla/pyjwt) | Authentication token issuance & validation | Fully Permissive | None |
| `redis` | `8.1.0` | MIT | [GitHub](https://github.com/redis/redis-py) | Async queue, caching, and event broker | Fully Permissive | None |
| `websockets` | `17.0.1` | BSD-3-Clause | [GitHub](https://github.com/python-websockets/websockets) | Real-time execution streaming | Fully Permissive | None |
| `croniter` | `6.2.4` | MIT | [GitHub](https://github.com/kiorky/croniter) | Cron schedule expression parser | Fully Permissive | None |
| `dukpy` | `0.6.0` | MIT | [GitHub](https://github.com/amol-/dukpy) | Embedded sandboxed JavaScript runtime | Fully Permissive | None |
| `psycopg2-binary` | `2.9.12` | LGPL with exception | [GitHub](https://github.com/psycopg/psycopg2) | PostgreSQL database driver | Dynamic link exception permitted | Low (Clean dynamic link) |
| `pymysql` | `1.2.0` | MIT | [GitHub](https://github.com/PyMySQL/PyMySQL) | MySQL connector backend | Fully Permissive | None |
| `pymongo` | `4.17.0` | Apache-2.0 | [GitHub](https://github.com/mongodb/mongo-python-driver) | MongoDB connector backend | Fully Permissive | None |
| `paramiko` | `5.0.0` | LGPL v2.1 | [GitHub](https://github.com/paramiko/paramiko) | SSH / SFTP connector operations | Dynamic link library | Low |
| `defusedxml` | `0.7.1` | Python-2.0 (PSFL) | [GitHub](https://github.com/tiran/defusedxml) | XML parser with XXE attack defenses | Fully Permissive | None |
| `aiofiles` | `25.1.0` | Apache-2.0 | [GitHub](https://github.com/Tinche/aiofiles) | Non-blocking file I/O operations | Fully Permissive | None |
| `python-multipart`| `0.0.32` | Apache-2.0 | [GitHub](https://github.com/Kludex/python-multipart) | Form data and multipart upload parser | Fully Permissive | None |
| `PyYAML` | `6.0.3` | MIT | [GitHub](https://github.com/yaml/pyyaml) | YAML workflow import/export parser | Fully Permissive | None |
| `email-validator` | `2.3.0` | Unlicense / CC0 | [GitHub](https://github.com/JoshData/python-email-validator) | Email syntax verification | Public Domain | None |
| `tzdata` | `2026.3` | Apache-2.0 | [GitHub](https://github.com/python/tzdata) | IANA time zone database | Fully Permissive | None |

---

## 2. Frontend Dependencies (`frontend/package.json`)

| Package | Version | License | Source / Repository | Purpose | Commercial Status | Copyleft Risk |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `react` | `19.2.8` | MIT | [GitHub](https://github.com/facebook/react) | UI component runtime | Permissive | None |
| `react-dom` | `19.2.8` | MIT | [GitHub](https://github.com/facebook/react) | Web DOM renderer | Permissive | None |
| `react-router-dom`| `7.18.2` | MIT | [GitHub](https://github.com/remix-run/react-router) | SPA client-side routing | Permissive | None |
| `@xyflow/react` | `12.11.2` | MIT | [GitHub](https://github.com/xyflow/xyflow) | Visual node graph canvas engine | Permissive | None |
| `zustand` | `5.0.14` | MIT | [GitHub](https://github.com/pmndrs/zustand) | Global state management | Permissive | None |
| `monaco-editor` | `0.56.0` | MIT | [GitHub](https://github.com/microsoft/monaco-editor) | Code and JSON schema editor | Permissive | None |
| `@monaco-editor/react`| `4.7.0` | MIT | [GitHub](https://github.com/suren-atoyan/monaco-react) | React bindings for Monaco | Permissive | None |
| `vite` | `8.2.0` | MIT | [GitHub](https://github.com/vitejs/vite) | Build tool & HMR dev server | Permissive (Dev) | None |
| `vitest` | `4.1.10` | MIT | [GitHub](https://github.com/vitest-dev/vitest) | Unit test runner | Permissive (Dev) | None |
| `@playwright/test`| `1.62.1` | Apache-2.0 | [GitHub](https://github.com/microsoft/playwright) | End-to-end browser testing | Permissive (Dev) | None |
| `oxlint` | `1.75.0` | MIT | [GitHub](https://github.com/oxc-project/oxc) | Ultra-fast linter | Permissive (Dev) | None |

---

## 3. Governance Directives

1. **No Strong Copyleft (AGPL / GPL)**: No core engine, node, connector, or API component may introduce AGPL or GPL dependencies.
2. **Proprietary Independence**: No proprietary asset, connector schema, or code structure from external commercial vendors (e.g. n8n, Zapier, Make) may be copied. All connectors in FlowSmith implement FlowSmith's own `ConnectorSDK` (`app.connectors`).
3. **Continuous License Validation**: Every dependency addition must be reviewed against this policy prior to merge.
