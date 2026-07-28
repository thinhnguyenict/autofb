# AutoFB

[Đọc tài liệu tiếng Việt](README_VI.md)

AutoFB is a legacy Facebook publishing tool that is being migrated into a secure,
multi-user application. The current code can publish legacy photo, ad, video and
Reels workflows; it is **not** a replacement for Meta's OAuth requirements.

## Security first

- Never commit `config.json`, `.env`, Facebook access tokens, app secrets, or
  third-party upload credentials. They are ignored by Git.
- Copy `config.json.example` locally and fill it with credentials obtained through
  Meta's approved OAuth/token flow.
- Rotate any credentials that were previously committed to repository history.
- Login identifiers are temporarily locked after five failed attempts in fifteen
  minutes; successful authentication clears the durable failure counter.
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
Repeated scheduling or immediate-publish requests for the same post reuse its
existing queued job, preventing duplicate delivery before a worker claims it.
Each worker poll claims at most `AUTOFB_WORKER_BATCH_SIZE` due jobs (default 10,
allowed range 1–100) in deterministic run-time order, preventing an accumulated
queue from creating an unbounded provider burst after downtime.
The Compose worker also waits `AUTOFB_WORKER_MIN_PUBLISH_INTERVAL_SECONDS`
(configured as one second) between post deliveries in a claimed batch. Set a
larger value when Meta signals tighter app/Page limits; accepted values are 0–60.
When Meta returns HTTP 429, the worker honors numeric and HTTP-date `Retry-After`
headers (capped at one hour) instead of immediately applying its normal
exponential retry; missing or invalid values fall back to 60 seconds.

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
curl -fsSL https://raw.githubusercontent.com/YOUR_ORG/YOUR_REPO/main/deploy/aapanel_ubuntu_24_04.sh | sudo env REPO_URL=https://github.com/YOUR_ORG/YOUR_REPO.git DOMAIN=tool.huongdancauca.com APP_DIR=/www/wwwroot/tool.huongdancauca.com bash
```

This pipe form is preferred over `bash <(curl ...)` on VPS shells because some
`sudo`/terminal combinations close the `/dev/fd/*` file descriptor before `bash`
can read it, causing `bash: /dev/fd/63: No such file or directory`.

If you already cloned the repository on the VPS, run:

```bash
sudo DOMAIN=tool.huongdancauca.com APP_DIR=/www/wwwroot/tool.huongdancauca.com bash deploy/aapanel_ubuntu_24_04.sh
```

The script installs Docker/Compose dependencies, writes a safe
`docker-compose.override.yml`, binds the API to `127.0.0.1:8001`, starts the API
and worker, and prints the aaPanel reverse-proxy target. By default it deploys
into `/www/wwwroot/tool.huongdancauca.com`.

If the VPS already has Docker CE repositories configured, the installer uses the
Docker CE packages (`docker-ce`, `docker-ce-cli`, `containerd.io`,
`docker-compose-plugin`) instead of Ubuntu's `docker.io` package to avoid the
common `containerd.io conflicts: containerd` apt resolver error.

The API binds to `127.0.0.1:8001` by default. If that port is busy, the installer
automatically tries `8002` through `8010`; set `AUTOFB_API_PORT=8011` if you need
a specific reverse-proxy port.

On a VPS, restart only the multi-tenant API and worker services:

```bash
docker compose up -d --build autofb-api autofb-worker
```

The legacy dashboard service is behind the `legacy` Compose profile so a generic
`docker compose up -d --build` will not try to bind the old `127.0.0.1:8000`
port and conflict with other services.

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
- `GET /readyz` (checks database access and writable media storage; returns 503 until ready)
- `GET /workerz` (checks that a worker heartbeat is recent; returns 503 when missing or stale)

The worker probe allows a five-minute heartbeat age by default. Override it with
`AUTOFB_WORKER_MAX_HEARTBEAT_AGE` when worker jobs normally take longer.

API requests emit single-line JSON logs containing a safe request ID, method,
path, response status and duration. Clients may send `X-Request-ID`; unsafe or
log-forging values are replaced, request bodies/query strings are never logged,
and the response echoes the accepted correlation ID.
All responses receive a restrictive Content Security Policy, permissions policy,
clickjacking/referrer protections and route-aware cache controls. After HTTPS is
confirmed end-to-end, set `AUTOFB_ENABLE_HSTS=1` to emit a one-year HSTS policy;
leave it disabled during plain-HTTP local development.
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/me`
- `GET` / `POST /api/v1/workspaces`
- `PUT /api/v1/workspaces/{workspace_id}/members`

Docker Compose stores both SQLite data and uploaded media in the shared
`autofb_api_data` volume so worker containers can read attachments and container
rebuilds do not discard uploaded files. The API container healthcheck uses
`/readyz`, while `/healthz` remains a lightweight process liveness probe.

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

If your Meta app review is not ready yet, workspace owners/admins can use the
dashboard's "Nhập Page token thủ công" form to import a Page ID, Page name and
Page access token. The API encrypts the Page token with
`AUTOFB_TOKEN_ENCRYPTION_KEY` and stores it without exposing the secret back to
the browser. This manual path is intended as an operational fallback; use the
OAuth flow for production user onboarding.

The dashboard also surfaces the workspace OAuth configuration status, including
which server-side environment variables are still missing, so operators can fix
Meta setup without digging through container logs.

Publish workers now record one durable `publish_results` row per attempt. The
dashboard shows both the queued jobs and the attempt history, including the Meta
remote post id on success or the saved error message on failure.

For urgent posts, the dashboard includes a "Tạo và đăng ngay" action that creates
a post and queues an immediate publish job without requiring a future schedule.

Failed posts can be retried from the dashboard. Retrying a failed post queues a
new immediate publish job while preserving the previous publish attempt history
for troubleshooting and audit review.

Uploaded media can be deleted from the dashboard before it is attached to a post,
which keeps the workspace media library clean without breaking existing posts.

Media writes now pass through a storage boundary that sanitizes filenames,
prevents path traversal, rejects empty/oversized uploads and removes partial files
after failure. Set `AUTOFB_MEDIA_MAX_BYTES` to change the default 100 MiB limit;
authorization is checked before any request can consume disk space.

Draft or failed posts can be edited or removed from the dashboard. Scheduled and
queued posts must be cancelled first so operators do not accidentally change work
that is still pending in the publish queue.

Unused Facebook Pages can be removed from the dashboard as long as no posts still
reference them, which prevents accidental deletion of Page tokens needed by
existing content.

Workspace owners and admins can rename workspaces and remove non-owner members
from the dashboard. The workspace owner account is protected from removal so each
workspace always keeps an accountable owner.

Signed-in users can update their display name and change their password from the
dashboard. Existing sessions are revoked after a password change, forcing a fresh
login with the new password.

The notification panel supports marking notifications as read and clearing only
read notifications so unread operational warnings remain visible.

Each workspace dashboard shows a compact summary of members, connected Pages,
media, posts, queued jobs and unread notifications.

Operators can duplicate any existing post from the dashboard to create a fresh
draft with the same body and media attachments, making recurring campaigns faster
to prepare without editing scheduled or published records in place.

The post list can be filtered by status (draft, scheduled, queued, published or
failed) so teams can focus on the queue state they need to review.

The dashboard includes a monthly calendar feed showing each scheduled post's
local display time, Fanpage, content and current delivery status. Calendar API
ranges are workspace-scoped and limited to one year per request.

Editors must submit drafts for approval before scheduling or immediate publishing.
Workspace owners/admins can approve or reject pending drafts with an optional
review comment; publishers and managers retain direct publishing permission.

Dashboard screenshots now require a real Playwright Chromium browser. Run
`make bootstrap` once, then `make screenshot`; the capture tool starts a temporary
local FastAPI server automatically when none is running. CI installs Chromium and
fails rather than silently accepting a synthetic fallback image.

Legacy spreadsheets can be migrated once with `make import-excel FILE=data.xlsx
ACTOR_EMAIL=admin@example.com WORKSPACE='Default workspace' DRY_RUN=1`. Required
columns are `facebook_page_id` and `body`; optional `scheduled_at` and `timezone`
columns create schedules. The importer validates every row before writing, and a
dry run is recommended before removing `DRY_RUN=1`.

Filtered post lists can also be exported as CSV from the dashboard for handoff,
review or simple backup before a campaign run.

The publish worker automatically requeues stale `running` jobs before each poll,
so an interrupted container restart does not leave due posts stuck forever.
Successful publish results and their job/post terminal states are committed in one
transaction. If an older interrupted worker already recorded a remote post ID,
stale-job recovery finalizes it instead of publishing the Facebook post again.

The dashboard also surfaces publish metrics for queued/running/succeeded/failed
jobs and publish results, giving operators a quick delivery health snapshot.

Facebook connections are labelled as healthy, expiring within seven days,
expired, or unknown. Workspace owners/admins can remove unused connections, while
connections whose Pages are referenced by posts remain protected for audit and
retry safety.

Owners/admins can run a live Meta diagnostic from the dashboard. The server
decrypts the stored connection token only in memory, calls Meta's `/me` endpoint,
stores a `valid`/`invalid` health result and never returns the token to the browser.

Workspace owners/admins can download a portable JSON export containing members,
Page metadata, media metadata, posts, schedules, delivery history and audit logs.
The export intentionally excludes OAuth tokens, Page tokens, password hashes,
session tokens, encryption keys and server-side media paths.

Workspace owners can permanently delete a workspace and its scoped content after
exporting it. Users can then erase their account after deleting every workspace
they own; login/session/notification data is removed and retained content history
is pseudonymised so audit references do not expose the former email or name.

Server operators can bootstrap the first account non-interactively with
`make create-admin` by setting `AUTOFB_ADMIN_EMAIL`, `AUTOFB_ADMIN_PASSWORD` and
optionally `AUTOFB_ADMIN_WORKSPACE`.

The aaPanel deployment helper also runs that bootstrap automatically when the
admin environment variables are present, keeping first-login setup reproducible.

Create a transactionally consistent SQLite backup while the API is running with
`make backup-db`. Backups are written to `AUTOFB_BACKUP_DIRECTORY` (default
`./backups`) and the newest `AUTOFB_BACKUP_KEEP` files are retained (default 7).
The tool checks both source and backup integrity and never copies raw WAL files.

For an encrypted HTTPS backup gateway or object-storage upload endpoint, configure
an upload URL containing a `{filename}` placeholder and run:

```bash
AUTOFB_OFFSITE_BACKUP_URL='https://backup.example/autofb/{filename}' \
AUTOFB_OFFSITE_BACKUP_TOKEN='replace-with-runtime-secret' make backup-offsite
```

The off-site command creates the same integrity-checked SQLite snapshot, performs
a full temporary restore drill, and only then uploads it with HTTP `PUT`. It sends
SHA-256 `Digest`/`X-AutoFB-SHA256` headers. Plain HTTP is rejected by default, and
the bearer token is read only at runtime. A failed drill prevents upload and makes
the backup container exit non-zero so the container platform can alert/restart it.

To automate one verified upload every 24 hours with Docker Compose, provide the
two off-site variables in the deployment environment and enable the backup
profile:

```bash
AUTOFB_OFFSITE_BACKUP_URL='https://backup.example/autofb/{filename}' \
AUTOFB_OFFSITE_BACKUP_TOKEN='replace-with-runtime-secret' \
docker compose --profile backup up -d autofb-backup
```

The backup container shares only the application data volume and runs the same
integrity/restore/checksum workflow every `AUTOFB_BACKUP_INTERVAL_SECONDS` (default
86,400 seconds). Invalid intervals below one minute are rejected to prevent an
accidental tight backup loop.

To restore, first stop the API and worker, then run
`make restore-db BACKUP=backups/autofb-YYYYMMDDTHHMMSSZ.db`. Restoring over an
existing database is refused unless `FORCE=1` is supplied; forced restores keep a
timestamped `*.pre-restore-*.db` safety copy and atomically replace the database
only after both source and restored files pass SQLite integrity checks.

Run a non-destructive recovery exercise at any time with:

```bash
make restore-drill BACKUP=backups/autofb-YYYYMMDDTHHMMSSZ.db
```

The drill restores into a temporary directory, opens the result read-only,
checks SQLite integrity and required AutoFB tables, reports key row counts and
schema version, then deletes the temporary copy. It never stops or replaces the
live database.

Expired sessions/OAuth states and old operational throttling, heartbeat and token
diagnostic records can be previewed with `make cleanup-db DRY_RUN=1` and removed
with `make cleanup-db`. Retention is one day for login-attempt records, seven days
for stale worker heartbeats and 90 days for token diagnostics; active sessions and
unexpired OAuth states are preserved.

Rotate the server-side Fernet key without exposing plaintext tokens by stopping
the API/worker, taking a verified backup, and running `make rotate-token-key` with
`AUTOFB_OLD_TOKEN_ENCRYPTION_KEY` and `AUTOFB_NEW_TOKEN_ENCRYPTION_KEY` in the
process environment. The tool decrypts every connection/Page token before writing
and updates all ciphertext in one transaction; any invalid old-key token rolls the
entire rotation back. Start services with the new key only after the command passes.

Before exposing a deployment, run `make preflight` inside the API environment.
The command verifies required Meta settings, an HTTPS OAuth callback, Fernet key
shape, a non-localhost HTTPS callback, database integrity/foreign keys, writable
media, the complete expected schema, at least one account and a recent worker
heartbeat. It prints only check names/statuses—never configured
secrets—and exits non-zero until every pilot prerequisite passes.
Preflight also requires a successful off-site backup recorded within the previous
48 hours. Backup failures persist only the exception type—not URLs, tokens or
provider response bodies—so operators can monitor failure state without leaking
upload credentials.

Monitoring systems can poll `GET /backupz`. It returns HTTP 200 only when the
latest recorded off-site backup succeeded within `AUTOFB_BACKUP_MAX_AGE` seconds
(48 hours by default); missing, stale, invalid or failed runs return HTTP 503
without exposing backup filenames, destinations or error details.

Set `AUTOFB_BACKUP_ALERT_URL` to an HTTPS webhook to receive a compact alert when
the backup container fails. `AUTOFB_BACKUP_ALERT_TOKEN` optionally adds bearer
authentication. Alert payloads include only the service/event name, failure type
and timestamp; backup paths, upload destinations, exception messages and secrets
are deliberately excluded. Alert delivery errors never replace the original
backup failure.

For hosted API error reporting, configure an HTTPS `AUTOFB_ERROR_WEBHOOK_URL`
and optional `AUTOFB_ERROR_WEBHOOK_TOKEN`. Unhandled API exceptions emit a
best-effort event containing only the correlation ID, HTTP method/path,
exception type and timestamp. Request bodies, query strings, exception messages
and credentials are never included, and reporting failures do not replace the
original application exception.
Identical method/path/exception fingerprints are reported at most once per
minute, and the in-memory fingerprint cache is bounded, preventing an exception
storm from flooding the receiver or growing API memory without limit.

Production preflight now requires both alert receiver URLs and rejects HTTP,
localhost or credential-bearing URLs. Configure `AUTOFB_BACKUP_ALERT_URL` and
`AUTOFB_ERROR_WEBHOOK_URL` with public HTTPS endpoints before running
`make preflight`; authentication belongs in the corresponding token variables,
not in URL user-info.

Media can now use either the default local volume or an S3-compatible object
store. Set `AUTOFB_MEDIA_BACKEND=s3`, `AUTOFB_S3_BUCKET`, and optionally
`AUTOFB_S3_PREFIX`, `AUTOFB_S3_ENDPOINT_URL`, and `AUTOFB_S3_REGION`; standard
AWS credential environment variables are consumed by boto3. Uploads are size
checked while being spooled, stored under opaque workspace-scoped keys, and
downloaded by the worker only while publishing. Deletion and reads reject objects
outside the configured bucket/prefix. Use MinIO's S3 endpoint for a self-hosted
deployment or omit the endpoint for AWS S3.
Both backends enforce canonical workspace keys and normalize POSIX/Windows upload
names, remove control characters, and cap stored filenames at 255 characters
before they reach the filesystem, S3 object key or Meta multipart request.

To move an existing local library after configuring S3, first run
`make migrate-media-s3 DRY_RUN=1`, then `make migrate-media-s3`. Each object is
uploaded before its database path is conditionally replaced; an object is removed
again if the database record changed concurrently. Add `DELETE_LOCAL=1` only
after a backup and successful migration verification to remove source files.

After deployment and `make preflight`, run
`make pilot-acceptance URL=https://autofb.example`. The external acceptance gate
requires `/healthz`, `/readyz`, `/workerz`, and `/backupz` to all return HTTP 200
with their expected status. The command rejects HTTP, credentials, paths, query
strings and fragments in production URLs, and prints only gate names/statuses—not
response bodies or deployment URLs.

The aaPanel installer writes all S3, off-site backup, alert receiver and hosted
error settings into the protected runtime `.env`, including when upgrading an
older installation whose file lacks newer keys. When an off-site destination is
configured it starts the backup Compose profile automatically; otherwise it
prints an explicit warning because `/backupz` and pilot acceptance cannot pass.
Production preflight also requires `AUTOFB_PUBLIC_URL` to be a clean HTTPS origin,
requires the OAuth callback to use the same host, and requires HSTS to be enabled.
The aaPanel installer therefore enables application HSTS by default; keep the
aaPanel reverse proxy on HTTPS before exposing the domain.
Preflight also requires at least one connected Facebook account, one imported
Page, and a successful live token diagnostic from the previous 24 hours. Run the
connection diagnostic from the workspace dashboard after OAuth setup; an expired
connection, stale check, latest failed check or Page-less connection blocks pilot
approval.

## One-line Ubuntu 24.04 installer

On a fresh Ubuntu 24.04 VPS, open a root shell and run the installer with one
command (replace the raw URL with this repository's URL):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/YOUR_ORG/YOUR_REPO/main/deploy/install_ubuntu_24_04.sh)"
```

Use `bash -c "$(curl ...)"` rather than `curl ... | bash` so the installer can
read answers from the terminal. It interactively asks for the domain, Git
repository, installation directory, local API port, optional aaPanel install,
Meta App credentials and optional first-admin account. Passwords and app secrets
are entered without echo and are never included in the confirmation summary.
