# Kyro

**A personal command center for turning intentions into completed work.**

Kyro is no longer an outreach dashboard. This repository is now a deliberately simple, fast workspace for one person who is building things, studying, running a business, and experimenting with automation.

## The idea

Most productivity tools give you more places to put work.

Kyro gives you one place to **decide, execute, and review**.

> **Make the important work obvious. Make the repetitive work automatic.**

The new Kyro has six surfaces:

- **Command** — the daily operating picture: workload, progress, active projects, automations and recent activity.
- **Today** — a deliberately small execution queue.
- **Projects** — outcomes, progress and the next move.
- **Automations** — background systems and their health.
- **Inbox** — frictionless capture for ideas before they disappear.
- **Insights** — execution metrics instead of vanity metrics.

## Why this version is different

The previous product was too dependent on backend bootstrapping and too narrowly defined around outreach.

This build starts with the product experience itself.

The application renders immediately and stores its demo state in browser localStorage. There is no login wall, API dependency, database requirement, cron requirement, or external service required to experience the product.

That makes the demo reliable on static hosting such as Vercel.

## Run it

Open `public/index.html` directly, or serve the repository with any static web server.

For example:

```bash
python3 -m http.server 8000 --directory public
```

Then open `http://localhost:8000`.

## Functional interactions

The current build includes:

- navigation between all six workspaces
- task creation
- task completion
- persistent browser state
- idea capture
- resettable demo data
- responsive desktop/tablet/mobile layouts
- project and automation views
- live activity presentation
- no startup dependency on an API

## Product architecture

The frontend is intentionally self-contained for the first release.

Next layers can be added without redesigning the interface:

1. authenticated workspaces
2. real database persistence
3. AI task planning
4. calendar integration
5. Gmail/Outlook integration
6. GitHub project activity
7. scheduled automations
8. natural-language commands
9. multi-agent execution
10. mobile/PWA support

## Design direction

Kyro is intentionally:

- dark
- quiet
- premium
- information-dense without being crowded
- closer to Linear / Notion / Raycast than a generic SaaS template
- keyboard-friendly
- responsive
- restrained with color

No gradients-for-the-sake-of-gradients. No fake enterprise dashboards. No giant marketing hero inside the product.

## Repository

```
Kyro-outreach/
└── public/
    └── index.html
```

The old server/API files can remain in the repository as historical scaffolding, but the new application does not depend on them.

## Roadmap

### Phase 1 — Core cockpit
Done.

### Phase 2 — Kyro brain
- natural language command bar
- AI prioritization
- automatic daily planning
- context-aware project summaries

### Phase 3 — Kyro hands
- Gmail actions
- calendar actions
- GitHub actions
- web research
- scheduled jobs

### Phase 4 — Kyro memory
- persistent workspace memory
- project knowledge
- personal operating preferences
- searchable activity history

### Phase 5 — Kyro autonomy
- approval-based agents
- recurring workflows
- failure recovery
- execution logs

Kyro should become the layer between **what you want done** and **the tools that actually do it**.
