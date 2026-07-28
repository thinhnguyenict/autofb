# AutoFB product migration roadmap

## Product boundary

AutoFB will use Meta's official OAuth flow to connect Facebook accounts. The
application must never collect or store a person's Facebook password. A workspace
can have several OAuth connections, and each connection can contribute multiple
Fanpages that the authorised Meta user is allowed to manage.

## Target architecture

```text
React/TypeScript dashboard -> FastAPI API -> PostgreSQL
                                      |-> encrypted token store
                                      |-> Redis queue -> publishing workers -> Meta Graph API
                                      |-> S3/MinIO media storage
```

Every business record is scoped to a workspace. Tokens are encrypted at rest and
are never returned by the browser API.

## Delivery phases

1. **Foundation and security**: remove secrets from tracked configuration, validate
   legacy configuration, repair worker entrypoints, add tests and document the
   migration. This change begins that phase.
2. **Identity and tenancy**: add users, workspaces, membership roles, sessions,
   audit logs and PostgreSQL migrations. The initial API/service contract and local
   SQLite development store are now implemented; PostgreSQL is the next persistence
   increment before production use.
3. **Meta connections**: implement OAuth state/callback handling, encrypted token
   storage, Page discovery/import, token health checks and reconnect flow.
4. **Content operations**: add media storage, draft posts, Page selection,
   scheduling, approvals and a calendar UI. Migrate Excel data through a one-time
   importer rather than using it as mutable production state.
5. **Reliable delivery**: replace direct script execution with queued publishing
   jobs, idempotency keys, retries, rate limiting, post history and central
   scheduling.
6. **Production readiness**: notifications, metrics, error tracking, backups,
   CI/CD, privacy/data deletion procedures and security review.

## Current progress (2026-07-25)

| Phase | Status | Remaining production work |
| --- | --- | --- |
| Foundation and security | Complete for the SQLite MVP | Rotate any historical provider credentials and complete an external security review. Atomic Fernet key rotation and durable login throttling are implemented. |
| Identity and tenancy | MVP complete | Replace SQLite with PostgreSQL migrations before horizontal scaling. |
| Meta connections | MVP complete | Configure and review the production Meta app. Live Graph API token diagnostics are implemented. |
| Content operations | MVP complete | Configure the production S3/MinIO bucket and lifecycle policy. Local and S3-compatible storage, approval workflow, monthly calendar and one-time Excel importer are implemented. |
| Reliable delivery | In progress | Add a shared queue, distributed rate limiting and provider-supported idempotency. Repeated requests reuse one queued job; bounded/paced batches and Meta Retry-After handling protect a single worker. |
| Production readiness | MVP complete | Configure the production alert receivers and complete an external security review. Secret-free hosted error and backup webhooks, restore gates, JSON logging, data export/erasure, worker monitoring and bounded operational-record cleanup are implemented. |

The current release is suitable for a controlled single-VPS pilot after Meta OAuth
credentials and HTTPS are configured, `make preflight` passes, and the external
`make pilot-acceptance URL=https://your-host` gate succeeds. It is not yet
the final horizontally scaled production architecture described above.

## Initial data model

- `users`, `workspaces`, `workspace_members`, `audit_logs`
- `oauth_connections`, `oauth_tokens`, `facebook_pages`, `page_access_tokens`
- `media_assets`, `posts`, `post_media`, `schedules`
- `publish_jobs`, `publish_results`, `notifications`, `token_health_checks`

The minimum roles are `owner`, `admin`, `editor`, `publisher`, and `viewer`.

## MVP acceptance criteria

- A user can create a workspace and invite an editor.
- An authorised OAuth connection can import one or more allowed Pages.
- An editor can create a media post draft and schedule it for a selected Page.
- A worker publishes asynchronously and records one durable result per attempt.
- Failed temporary deliveries retry without duplicate posts.
- A user cannot read another workspace's Pages, media, posts, logs or tokens.

## Implemented OAuth connection slice

The API now generates one-time, ten-minute state values bound to an authorised
workspace manager. The Meta callback exchanges the code server-side, encrypts the
returned user/Page tokens with a required Fernet key, stores the connection inside
the workspace, and exposes page metadata without returning access tokens. A Meta
app configuration, callback URL, permission/app-review verification and production
PostgreSQL migration are still required before enabling this flow for users.
