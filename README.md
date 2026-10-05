# Kyro Outreach

Kyro Outreach is an approval-first outreach workspace for Kcreatives. This repository contains a runnable web application, a Python standard-library HTTP/API server, a tenant-scoped SQLite database, password/session authentication, a Resend email adapter, a secured scheduler endpoint, and a responsive browser UI.

## Run locally

Requirements: Python 3.11+ (Python 3.13 is supported); no third-party packages are required.

```bash
cp .env.example .env
python3 server.py
```

Open `http://localhost:8000`. Select **Enter DEMO MODE** to explore the fictional workspace, or choose **Create owner workspace** to register a private account. The demo workspace is clearly labeled, uses reserved `.example` addresses, and cannot deliver email. Demo send buttons only simulate sends.

The app creates `data/kyro.sqlite3` on first start. Keep the database and `.env` private. To start with a clean local database, stop the server and remove the database file.

### Docker

```bash
docker build -t kyro-outreach .
docker run --rm -p 8000:8000 -v kyro-data:/app/data \
  -e RESEND_API_KEY=... -e RESEND_FROM_EMAIL=... \
  -e CRON_SECRET=... -e REPLY_WEBHOOK_SECRET=... \
  kyro-outreach
```

The Docker image defaults to demo mode off and secure cookies on; use HTTPS at the ingress and persist `/app/data`.

## Live email setup

1. Create and verify a sending domain with Resend.
2. Set `RESEND_API_KEY` and `RESEND_FROM_EMAIL` in the server environment (never in browser code).
3. Set a sender name/email and a test recipient in Settings.
4. Send a clearly labelled test message and verify deliverability before enabling a campaign.
5. Set `COOKIE_SECURE=true` behind HTTPS.

If the provider is not configured, Kyro remains usable for prospect management, campaigns and draft approval; the send endpoint returns **Email provider not connected** and does not reserve/consume quota. Test sends are separate from outreach quota.

## Scheduler

`POST /api/cron/run` is the secure, repeatable worker entry point. Configure `CRON_SECRET` and invoke the endpoint from a trusted cron provider with:

```http
Authorization: Bearer <CRON_SECRET>
```

The worker selects due, approved jobs from active campaigns and repeats the same server-side eligibility checks as a manual send. It is safe to invoke more than once: database reservations, stable idempotency keys, and the unique successful-send constraint prevent duplicate outreach. Schedule frequent runs (for example, every 5 minutes); the application does not run a hidden, unbounded background loop.

## Reply events

Set `REPLY_WEBHOOK_SECRET` to enable the provider-neutral reply callback at `POST /api/webhooks/reply`. A trusted provider adapter should verify the provider's native signature first, then call Kyro using this canonical payload and bearer secret:

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

## Database / deployment notes

SQLite WAL mode is suitable for local and modest single-instance deployments. For multi-instance or high-volume production, port the schema and transaction boundaries to PostgreSQL (including a database-level atomic quota reservation) before running multiple app nodes. Put the app behind TLS, use a managed secrets store, back up the database, configure a verified sending domain, and monitor webhook/cron delivery. No provider secret is returned by an API route.

## Verification

Run the backend checks with:

```bash
python3 -m unittest discover -s tests -v
```

The safeguard suite exercises concurrent quota enforcement and failed-send accounting against an isolated temporary database with a fake provider; it never sends real email.
