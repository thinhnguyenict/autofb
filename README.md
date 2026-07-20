# AutoFB

AutoFB is a legacy Facebook publishing tool that is being migrated into a secure,
multi-user application. The current code can publish legacy photo, ad, video and
Reels workflows; it is **not** a replacement for Meta's OAuth requirements.

## Security first

- Never commit `config.json`, `.env`, Facebook access tokens, app secrets, or
  third-party upload credentials. They are ignored by Git.
- Copy `config.json.example` locally and fill it with credentials obtained through
  Meta's approved OAuth/token flow.
- Rotate any credentials that were previously committed to repository history.
- Change the dashboard password using the `APP_PASSWORD_HASH` environment variable
  before exposing it to a network.

## Local Docker dashboard

```bash
cp config.json.example config.json
# Edit config.json locally; do not commit it.
docker compose up --build
```

Open <http://localhost:8000> for the legacy dashboard and <http://localhost:8001/docs>
for the new multi-tenant API. The API currently provides account/session and
workspace membership foundations; Meta OAuth, Page discovery, content scheduling
and workers are the following delivery slices. Publishing workers must be started
separately until the queue-based application migration is complete.

## FastAPI and Playwright developer tools

The repository includes small tools for local API and dashboard verification:

```bash
python tools/bootstrap_dev_tools.py
python tools/fastapi_smoke.py
AUTOFB_DASHBOARD_URL=http://127.0.0.1:8001 python tools/capture_dashboard.py
```

`tools/bootstrap_dev_tools.py` installs `reqs.txt` and the Playwright Chromium
browser. `tools/fastapi_smoke.py` boots the FastAPI app through `TestClient`
against a temporary SQLite database when FastAPI is installed; otherwise it runs
the same registration/login/workspace/member contract through the service layer
so the command still validates core behavior in dependency-restricted containers.
`tools/capture_dashboard.py` uses Playwright to save a screenshot of a running
dashboard to `output/dashboard.png` by default and writes a dependency-free PNG
fallback artifact when Playwright is unavailable.

Common commands are also available as Make targets:

```bash
make test
make check
make smoke
make screenshot
```

## One-command VPS install for aaPanel/Ubuntu

For an Ubuntu 24.04 VPS managed by aaPanel and serving
`tool.huongdancauca.com`, use the deployment helper:

```bash
REPO_URL=https://github.com/YOUR_ORG/YOUR_REPO.git bash <(curl -fsSL https://raw.githubusercontent.com/YOUR_ORG/YOUR_REPO/main/deploy/aapanel_ubuntu_24_04.sh)
```

If you already cloned the repository on the VPS, run:

```bash
sudo DOMAIN=tool.huongdancauca.com APP_DIR=/www/wwwroot/tool.huongdancauca.com bash deploy/aapanel_ubuntu_24_04.sh
```

The script installs Docker/Compose dependencies, writes a safe
`docker-compose.override.yml`, binds the API to `127.0.0.1:8001`, starts the API
and worker, and prints the aaPanel reverse-proxy target. By default it deploys
into `/www/wwwroot/tool.huongdancauca.com`.

## Legacy configuration contract

`config.json` contains Excel locations and arrays for Page IDs, Page names and
Page access tokens. The Page ID and token lists must have exactly the same length;
Page names are optional except for the legacy ad workflow, where they are required.
The shared loader validates this before a worker sends a request.

## Development direction

The target product is a multi-tenant application with workspace-level roles,
Facebook OAuth connections, encrypted token storage, a Postgres-backed content
calendar, asynchronous publishing workers and an audit trail. See
[`docs/product-roadmap.md`](docs/product-roadmap.md) for the staged implementation
plan.

## Multi-tenant API foundation

The new API is intentionally a small first slice of the migration. It stores users,
workspaces, membership roles, opaque sessions and audit events in an isolated local
SQLite database (`AUTOFB_DATABASE_PATH`; default `./autofb.db`). This allows the
identity and authorization contract to be tested before the upcoming PostgreSQL
migration and Meta OAuth integration.

Available endpoints:

- `GET /healthz`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/me`
- `GET` / `POST /api/v1/workspaces`
- `PUT /api/v1/workspaces/{workspace_id}/members`

Authenticated requests use `Authorization: Bearer <access_token>`. Tokens are
opaque random values; only their SHA-256 digest is stored in the database.

## Meta OAuth configuration

The API uses the official server-side OAuth callback flow; it never accepts a
Facebook password. Before enabling the connect endpoint, configure these API
container environment variables with values from the Meta app configuration:

```text
META_APP_ID
META_APP_SECRET
META_REDIRECT_URI
AUTOFB_TOKEN_ENCRYPTION_KEY
```

`AUTOFB_TOKEN_ENCRYPTION_KEY` must be a Fernet key. The callback exchanges the
one-time OAuth code server-side, encrypts user/Page access tokens before storage,
and imports only Pages returned by Meta for the authorized connection.
