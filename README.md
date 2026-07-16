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

Open <http://localhost:8000>. The container starts the legacy PHP dashboard only.
Publishing workers must be started separately until the queue-based application
migration is complete.

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
