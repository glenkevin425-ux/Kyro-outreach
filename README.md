# Kyro — Client Acquisition OS

Kyro is a lightweight operating system for a small agency that wants a cleaner path from **prospect → conversation → client**.

It is built for Kcreatives, but the product is workspace-based: keep a prospect pipeline, group prospects into campaigns, generate grounded first drafts, approve messages, schedule them, monitor the queue and measure outcomes.

This is **not** an autonomous spam bot. Kyro is designed around controlled, human-approved outreach.

## Product

> **Kyro is the command center for client acquisition.**

- **Command Center** — daily capacity, funnel, queue and recent activity.
- **Pipeline** — prospects, search, statuses, notes and CSV import.
- **Campaigns** — controlled outreach sequences with daily caps.
- **Message Lab** — grounded message generation and editing.
- **Queue** — approved and scheduled work that is allowed to leave.
- **Insights** — recorded sends, replies, interest and service performance.
- **Workspace** — sender identity, timezone, sending window and provider state.

The interface was rebuilt around these workflows while retaining the backend safeguards that make the system functional: workspace scoping, approval gates, suppression checks, scheduling, idempotent sends and the 10-send hard ceiling.

## Run locally

Requirements: Python 3.11+.

~~~bash
python3 server.py
~~~

Open `http://localhost:8000`.

The deployment-stage demo workspace is available automatically. Demo emails are simulated and never delivered.

Local development uses SQLite at `data/kyro.sqlite3`.

## Vercel

The project uses `public/index.html` for the web application, `api/index.py` as the Vercel Python/ASGI entry point, and `server.py` for application/API logic.

Set `DATABASE_URL`, `COOKIE_SECURE=true`, `APP_URL`, and `CRON_SECRET` in Vercel. For live email also configure `RESEND_API_KEY` and `RESEND_FROM_EMAIL`.

SQLite is deliberately rejected in Vercel because serverless function storage is not durable.

The repository does not declare a sub-daily Vercel Cron schedule. The worker endpoint remains available at `/api/cron/run` for a trusted external scheduler using `Authorization: Bearer <CRON_SECRET>`.

## Core workflow

### 1. Add prospects
Add prospects individually from Pipeline or import CSV. Supported headers:

~~~text
business_name,contact_name,email,phone,website,industry,location,notes,source
~~~

Kyro normalizes email addresses and prevents duplicate contacts inside a workspace.

### 2. Create a campaign
A campaign defines the service focus, daily limit, sending window, follow-up timing and selected prospects. The campaign limit can never exceed the global 10-send ceiling.

### 3. Create a message
Message Lab uses the prospect record plus an optional verified observation. The current generator is deterministic and does not invent company facts.

### 4. Approve
A generated message remains a draft until the operator explicitly approves it. Approval is separate from scheduling and sending.

### 5. Schedule or send
Scheduled messages enter Queue. Manual sends still pass every server-side check: prospect eligibility, suppression status, campaign membership, active campaign, recent-contact protection, sending window, campaign quota, workspace quota and idempotency protection.

### 6. Measure
Insights only display events Kyro actually recorded. The application does not fabricate opens, clicks or delivery metrics.

## Safety model

Kyro has a hard maximum of **10 successful outreach sends per calendar day per workspace**.

Other safeguards include human approval, 30-day recent-contact protection, suppression lists, reply/interest stop conditions, campaign-level caps, sending windows, idempotent reservations, failure accounting, workspace-scoped queries, CSRF protection and secure session cookies.

The demo workspace is isolated from real delivery.

## API

~~~text
GET  /api/bootstrap
GET  /api/dashboard
GET  /api/prospects
POST /api/prospects
GET  /api/campaigns
POST /api/campaigns
POST /api/drafts/generate
POST /api/drafts
POST /api/drafts/:id/approve
POST /api/drafts/:id/schedule
POST /api/drafts/:id/send
GET  /api/queue
GET  /api/analytics
GET  /api/settings
PUT  /api/settings
GET  /api/suppressions
POST /api/suppressions
GET  /healthz
~~~

## Structure

~~~text
Kyro-outreach/
├── api/index.py
├── public/index.html
├── server.py
├── requirements.txt
├── vercel.json
├── Dockerfile
├── .env.example
└── README.md
~~~

## Product direction

Future upgrades should extend the safety model rather than bypass it:

1. business research connectors
2. provider-native reply/webhook adapters
3. richer campaign segmentation
4. contact enrichment
5. source-grounded AI personalization
6. client/project conversion tracking
7. recurring reporting
8. external scheduler integration
9. multi-user workspace roles

## Verification

~~~bash
python3 -m unittest discover -s tests -v
~~~

Health check: `GET /healthz`.

Before live sending, verify PostgreSQL connectivity, a verified sending domain, sender identity, test recipient, worker secret, secure cookies, suppression behavior, daily quota and provider response handling.

**Kyro / Kcreatives**

Design. Strategy. Growth.