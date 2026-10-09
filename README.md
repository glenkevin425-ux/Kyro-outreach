# Kyro — Personal Command Center

Kyro is a free, local-first personal command center for tasks, projects, finance, ideas and goals. The core runs in the browser without a backend, account, API key, required AI provider or runtime dependency.

## Features

- Dashboard with daily overview and progress indicators.
- Tasks with create/edit/complete/reopen/delete, search and filters.
- Projects and goals with progress tracking.
- Ideas with edit support.
- Income allocation plus a separate expense ledger and monthly balance.
- Workspace command palette and activity history.
- Undo for deletions and a periodic local backup reminder.
- Responsive mobile navigation, keyboard shortcuts and fullscreen control.
- JSON backup export/import.
- Baseline Content Security Policy and no external Google Fonts dependency.

## Run locally

You can open `public/index.html` directly, or serve the app from the repository root:

```bash
python -m http.server 4173 --directory public
```

Then open `http://localhost:4173`.

## Validate changes

The app itself has no runtime dependencies. Browser tests use Playwright as a development-only dependency:

```bash
npm install
npm run check
npx playwright install chromium
npm run test:e2e
```

GitHub Actions installs Chromium, runs the static checks, and runs the browser smoke suite on pushes and pull requests.

## Data and privacy

Kyro stores workspace data in this browser's `localStorage`. Data is not automatically synced across devices. Use **Activity → Export backup** to download a JSON backup and store it somewhere safe. Import restores a previous backup. Clearing browser site data can delete the local workspace.

## Project files

- `public/index.html` — HTML shell and security metadata.
- `public/styles.css` — styles and responsive layout.
- `public/app.js` — state, rendering and interaction logic.
- `scripts/check.js` — static checks.
- `.github/workflows/ci.yml` — automated checks.
- `PROJECT_BRIEF.md` — implementation constraints and test checklist.
- `ROADMAP.md` — phased product plan.

## Design principles

Build the reliable version first. Keep the interface light, responsive and premium; keep the data local by default; make AI optional rather than a dependency; ship small, testable improvements instead of fragile rewrites.
