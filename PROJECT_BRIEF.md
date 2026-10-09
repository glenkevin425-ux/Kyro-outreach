# Kyro project brief

Read this before changing the application. Make small, focused changes and preserve user data.

## Product

Kyro is a free, single-user, local-first command center for tasks, projects, finance, ideas, goals and activity. It is not an AI agent. Core features must not require an account, backend, API key, paid service or external AI provider.

## Architecture

- `public/index.html`: document shell, metadata and local asset references.
- `public/styles.css`: responsive visual system and motion.
- `public/app.js`: application state, views, forms, actions, rendering and local persistence.
- `scripts/check.js`: dependency-free syntax and invariant checks.
- `scripts/serve.js`: dependency-free static server for browser tests.
- `tests/kyro.spec.js` and `playwright.config.js`: Playwright smoke suite.
- `package.json`: development-only test tooling; nothing is required at runtime.
- `.github/workflows/ci.yml`: runs static checks and browser tests on pushes and pull requests.

Run locally by opening `public/index.html` or serving the `public` directory. Run `npm run check` before committing; run `npm run test:e2e` for browser smoke tests after installing dependencies and Chromium.

## Hard rules

1. Keep runtime plain HTML/CSS/JavaScript. No runtime dependencies, backend, required AI, or API keys.
2. Preserve the finance allocation ratio and exact integer arithmetic. The October 2026 demo income is KSh 31,450: Needs 14,467, Savings 8,177, Business 5,032, Other 3,774. The four allocations must sum to the income amount.
3. Expenses are an explicit separate model; do not silently treat allocations as expenses.
4. Do not add inline `onclick` handlers. Use delegated listeners and `data-action`, `data-view`, and `data-form`.
5. Escape all user-provided strings before interpolating them into `innerHTML`.
6. State changes must go through `commit()` so persistence, rendering and activity history remain consistent.
7. Keep the `kyro.v2` localStorage key for compatibility. The stored data schema is version 3; handle older versions through explicit migrations.
8. Respect `prefers-reduced-motion`, keyboard navigation and focus visibility.
9. Keep the UI light, clean, responsive and premium. Do not introduce an AI-agent interface or change the product into a dark theme.
10. No destructive change may silently discard existing data. Keep export/import usable.

## State shape

```js
{
  v: 3,
  view,
  tasks: [{ id, title, due, pri, done }],
  projects: [{ id, name, pct }],
  income: [{ id, month, source, amount, alloc }],
  expenses: [{ id, month, description, category, amount }],
  ideas: [{ id, text }],
  goals: [{ id, name, pct }],
  activity: [{ id, text, at }]
}
```

The browser's localStorage is the primary store. Export/import is the user's manual backup path. Reminders should be helpful, rate-limited and dismissible through normal browser interaction.

## Current functionality

- Dashboard with date-aware greeting, progress rings and workspace summary.
- Task create/edit/complete/reopen/delete, search and filters by deadline, priority and status.
- Project create/edit/progress/delete.
- Goal create/edit/progress/delete.
- Idea create/edit/delete.
- Income and expense records with editing and deletion.
- Monthly income allocation and expense/remaining-balance summaries.
- Workspace command palette including tasks, projects, goals, ideas, income and expenses.
- Responsive desktop sidebar and mobile navigation.
- Fullscreen control, keyboard shortcuts, import/export, activity log.
- Undo for deletion, modal focus handling and periodic backup reminder.
- Baseline Content Security Policy and system-font fallback.

## Test checklist

- Run `node scripts/check.js`.
- Open each view and test navigation on desktop and mobile widths.
- Create, edit, complete, reopen, delete and undo a task.
- Create/edit/delete/undo project, goal, idea, income and expense records.
- Confirm October's seeded allocation sums to KSh 31,450.
- Confirm expense totals and remaining balance change after edits/deletes.
- Refresh and confirm saved state persists.
- Export a backup, reset only with explicit confirmation, and import the backup.
- Test Escape, Tab and Shift+Tab in modals, focus restoration, reduced motion and keyboard-only navigation.
- Check the browser console and network panel for errors or unexpected external requests.

## Change protocol

1. Inspect current code and this brief before editing.
2. Make focused changes rather than replacing whole files from older snapshots.
3. Run the static checks after every JavaScript change.
4. Test actual browser behavior before claiming runtime verification.
5. Update this brief when the architecture or state shape changes.
