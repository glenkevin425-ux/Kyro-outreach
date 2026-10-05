# Kyro Outreach

Kyro Outreach is an approval-first outreach workspace for Kcreatives. This repository contains a responsive browser UI, the existing local Python HTTP/SQLite server, a Vercel Python ASGI entrypoint, a SQLite/PostgreSQL storage adapter, password/session authentication, a Resend email adapter, and a secured scheduled-worker endpoint.

## Run locally

Requirements: Python 3.11+ (Python 3.13 is supported). Local SQLite development uses only the Python standard library; install `requirements.txt` only when connecting to PostgreSQL.

```bash
cp .env.example .env
python3 server.py
```

Open `http://localhost:8000`. Select **Enter DEMO MODE** to explore the fictional workspace, or choose **Create owner workspace** to register a private account. The demo workspace is clearly labeled, uses reserved `.example` addresses, and cannot deliver email. Demo send buttons only simulate sends.

The app creates `data/kyro.sqlite3` on first local start. Keep the database and `.env` private. To start with a clean local database, stop the server and remove the database file.

### Docker

```bash
docker build -t kyro-outreach .
docker run --rm -p 8000:8000 -v kyro-data:/app/data \
  -e RESEND_API_KEY=... -e RESEND_FROM_EMAIL=... \
  -e CRON_SECRET=... -e REPLY_WEBHOOK_SECRET=... \
  kyro-outreach
```

The Docker image defaults to demo mode off and secure cookies on; use HTTPS at the ingress and persist `/app/data`.

## Prepare / deploy on Vercel

The repository includes `api/index.py` (an ASGI app recognized by Vercel's Python Functions runtime) and `vercel.json` (API rewrites, static UI routing, function duration, and the secured Cron schedule). The original `python server.py` + SQLite workflow remains available locally.

1. Import the public GitHub repository `glenkevin425-ux/Kyro-outreach` into Vercel.
2. Attach a managed PostgreSQL database (Neon or Supabase; use the provider's pooled connection string where available) and expose it as `DATABASE_URL`. `POSTGRES_URL` is also accepted. The Vercel runtime refuses to fall back to SQLite because function filesystems are not durable.
3. Add production environment variables in Vercel **without committing secrets**:
   - `DATABASE_URL` — managed PostgreSQL connection string.
   - `KYRO_DEMO_ENABLED=false` — disable the clearly labeled demo workspace in production.
   - `COOKIE_SECURE=true` and `APP_URL=https://<your-domain>`.
   - `CRON_SECRET` — a long random secret; Vercel Cron sends it as `Authorization: Bearer <CRON_SECRET>`.
   - `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, and optionally `REPLY_WEBHOOK_SECRET` only if live provider functions are being configured.
4. Deploy. On the first API request, Kyro creates its schema in the managed database. This does **not** import or migrate local SQLite records; a new Vercel database starts empty.
5. Confirm the deployment, database connectivity, owner setup, email provider, secure cookies, and cron authorization before enabling a live campaign.

The configured worker runs every five minutes. Vercel currently restricts Hobby Cron to once per day; this schedule therefore requires a plan that supports sub-daily Cron (currently Pro or higher; see [Vercel Cron plan limits](https://vercel.com/docs/cron-jobs/usage-and-pricing)). The daily Hobby cadence is not an equivalent scheduler for intraday send windows. If deploying on Hobby, remove the `crons` block and use a trusted external scheduler at an appropriate cadence; keep `CRON_SECRET` authorization enabled.

Vercel functions are stateless and the database stores durable transactional state. PostgreSQL advisory transaction locks serialize send-quota and login-rate-limit critical sections across concurrent function instances. The successful-send ceiling, idempotency, and failure accounting remain server-enforced.

## Live email setup

1. Create and verify a sending domain with Resend.
2. Set `RESEND_API_KEY` and `RESEND_FROM_EMAIL` in the server environment (never in browser code).
3. Set a sender name/email and a test recipient in Settings.
4. Send a clearly labelled test message and verify deliverability before enabling a campaign.
5. Use `COOKIE_SECURE=true` behind HTTPS.

If the provider is not configured, Kyro remains usable for prospect management, campaigns and draft approval; the send endpoint returns **Email provider not connected** and does not reserve/consume quota. Test sends are separate from outreach quota.

## Scheduler

`/api/cron/run` is the secure, repeatable worker entry point. Vercel Cron invokes it with `GET`; `POST` is also supported for trusted schedulers. Configure `CRON_SECRET` and send:

```http
Authorization: Bearer <CRON_SECRET>
```

Vercel Cron supplies that Bearer header when the project environment variable is named `CRON_SECRET`. Requests without a configured matching secret are rejected. The worker selects due, approved jobs from active campaigns and repeats the same server-side eligibility checks as a manual send. It is safe to invoke more than once: database reservations, stable idempotency keys, and the unique successful-send constraint prevent duplicate outreach. The app does not run a hidden, unbounded background loop.

## Reply events

Set `REPLY_WEBHOOK_SECRET` to enable the provider-neutral `POST /api/webhooks/reply` endpoint. A trusted provider adapter should verify the provider's native signature first, then call Kyro using this canonical payload and bearer secret:

```json
{"event_id":"provider-event-id","workspace_id":"workspace-id","prospect_email":"contact@example.com","status":"Replied","note":"Optional internal summary"}
```

Supported statuses are `Replied`, `Interested`, `Not Interested`, and `Do Not Contact`. Events are idempotent; a match updates the prospect, writes an audit event, cancels pending follow-ups and queued sends, and adds a suppression for `Do Not Contact`. The callback intentionally does not guess how arbitrary provider payloads should be verified or mapped.

## Safety and data behavior

- **Global ceiling:** the server hard-caps successful outreach at 10 per calendar day in the workspace timezone. Initial messages, follow-ups, manual sends and scheduled jobs share the same atomic quota reservation.
- **Failures:** provider failures release the reservation and do not increment the successful-send counter.
- **Approval:** drafts start as `Draft`; explicit approval is required before scheduling or sending. AI-generated drafts are not automatically sent.
- **Suppression / replies:** normalized addresses are checked against a workspace suppression list, and reply/interested/not-interested states stop pending follow-ups.
- **Research:** the built-in draft generator is a grounded, deterministic template. It interpolates only the prospect record and the optional user-entered verified observation. It does not scrape websites or invent company facts. No AI provider is currently wired; `AI_API_KEY` is reserved and has no effect.
- **Analytics:** figures are derived from Kyro's recorded database events. Provider delivery/open/click metrics are not fabricated.
- **Authentication:** passwords use PBKDF2-SHA256; sessions are random, stored as hashes, HttpOnly and SameSite=Lax. Mutating requests use a session-bound CSRF token. All record queries include the authenticated user/workspace scope.

## Database notes

- Local development uses SQLite in `data/kyro.sqlite3`; Docker deployments need a persistent volume.
- Vercel uses PostgreSQL via `DATABASE_URL`/`POSTGRES_URL`. SQLite is deliberately rejected on Vercel. The database schema is initialized lazily on the first API request.
- Local-to-managed database migration is not automatic. Preserve existing local data separately and move it only through a deliberate, verified migration process.
- Keep database/provider secrets in environment configuration, back up the managed database, use a verified sending domain, and monitor scheduled-worker and reply-webhook delivery. No provider secret is returned by an API route.

## Verification

Run the backend checks with:

```bash
python3 -m unittest discover -s tests -v
```

The safeguard suite exercises concurrent quota enforcement and failed-send accounting against an isolated temporary database with a fake provider; it never sends real email.
