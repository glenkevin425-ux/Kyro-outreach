# Kyro — Personal Command Center

Kyro is a **free, local-first personal command center** for one person.

It is not an AI agent and does not require Anthropic, OpenAI, API keys, or an external inference service.

## The idea

One place to see, organize, and manage the things that matter:

- **Dashboard** — your day at a glance
- **Tasks** — work to do today and later
- **Projects** — active projects and progress
- **Finance** — income and simple financial overview
- **Ideas** — capture ideas before they disappear
- **Goals** — track bigger objectives
- **Activity** — see what you have recently done

## V1 principles

1. **Free to run**
2. **Personal by default**
3. **No external AI dependency**
4. **Simple and predictable**
5. **Useful before clever**
6. **Small changes over fragile rewrites**

The first version stores its data locally in the browser using `localStorage`.

## Architecture

```text
Kyro
│
├── Dashboard
├── Tasks
├── Projects
├── Finance
├── Ideas
├── Goals
└── Activity
        │
        ↓
   Local browser state
```

There is deliberately no command parser, LLM brain, agent loop, MCP layer, or API requirement in V1.

## Design direction

**White + vibrant**

The interface is intentionally clean, bright, premium, and information-dense without becoming cluttered.

Visual references include Apple, Linear, Notion, Raycast, Stripe, and Vercel, but the UI is original.

## Current branch

`kyro-personal-command-center`

This branch is the new Personal Command Center build. `main` remains untouched.

## V1 functionality

- Dashboard with live stats
- Time-based greeting
- Task creation
- Task completion/reopening
- Task priorities
- Task due grouping
- Project creation
- Project progress
- Income logging
- Income totals
- Idea capture/deletion
- Goal creation
- Goal progress
- Activity history
- Responsive mobile navigation
- Local persistence

## Future possibilities

Only after V1 proves useful:

- calendar/deadline view
- expenses and budgets
- recurring tasks
- study workspace
- richer project pages
- data export/import
- cloud sync
- authentication
- optional AI features

AI should remain an **optional layer**, never a requirement for the core product.

## Development rule

Build the boring, reliable version first.

Do not reintroduce an agent architecture merely because it sounds more advanced.