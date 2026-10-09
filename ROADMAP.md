# Kyro roadmap

Kyro's product goal is a fast, private, local-first command center for student-founders, with practical Kenya-first finance support. Keep the free core useful without accounts, tracking, API keys or paid services.

## Phase 1 — Foundation and trust

### Implemented in the current codebase
- Local-first state with explicit version 2 to version 3 migration.
- Editing across tasks, projects, goals, ideas, income and expenses.
- Task search and deadline/priority/status filters.
- Command palette search across workspace records, including finance records.
- Separate expense model and monthly remaining-balance summary.
- Undo for record deletions.
- Keyboard focus trapping and focus restoration for modal forms.
- Rate-limited backup reminder with a direct export action.
- Baseline Content Security Policy and removal of the external Google Fonts dependency.
- Dependency-free JavaScript, finance invariant and asset checks.
- GitHub Actions workflow to run static checks on pushes and pull requests.

### Still to verify or complete
- Run the browser-level smoke checklist on desktop and phone-sized viewports.
- Add automated browser tests for critical flows when the test harness is ready.
- Audit keyboard-only use, focus order, labels, contrast and screen-reader announcements.
- Verify storage quota failures and malformed backup handling in a browser.
- Measure Lighthouse performance and accessibility scores rather than guessing.
- Confirm the deployed site is serving the latest commit.

**Exit criteria:** no known data-loss issues, checks are green, and critical workflows are tested in a real browser.

## Phase 2 — Flagship features

1. **M-Pesa import:** parse pasted SMS or statement data locally; preview and confirm transactions before saving.
2. **Weekly review:** review completed and overdue tasks, money in/out, and one goal to prioritize.
3. **Focus mode:** a 25-minute timer attached to a task, with a local record of focus sessions.
4. **Calendar and recurring tasks:** real due dates, week/month views and recurring schedules.
5. **Themes and language:** optional dark theme, accent customization, and English/Swahili UI.

Each feature must work offline, have tests and preserve existing user data.

## Phase 3 — Platform

- Installable PWA with manifest and service worker.
- Optional cross-device sync only after local-first behavior is dependable.
- Browser testing across Chrome, Safari and Firefox at real mobile sizes.
- Consider splitting files or introducing a build tool only when the current structure becomes a genuine constraint.
- Privacy-respecting analytics only if opt-in and clearly disclosed.

## Phase 4 — Launch

- Publish clear screenshots and a short demo video.
- Write a concise founder story and onboarding guide.
- Invite a small group of real users and collect feedback before a larger launch.
- Add license, contribution guidance and issue templates if the repository is made public for contributors.

## Phase 5 — Sustainability

Possible later options include shareable templates, calendar export, CSV import/export and optional sync. Any AI feature must be opt-in and never required for the core product.

## Definition of done

- Works at desktop and phone widths.
- Works with keyboard-only navigation and reduced motion.
- Includes a test or an explicit manual test step.
- Passes `node scripts/check.js` and CI.
- Preserves existing saved data and the finance allocation invariant.
- Updates this roadmap/brief if project structure or data shape changes.

## Do not do

- Do not replace current code with an older ZIP snapshot without reconciling feature differences.
- Do not add required AI, tracking, account creation or paid services.
- Do not claim performance, accessibility or deployment results without measuring them.
- Do not build more features while a known data-loss or core interaction bug remains.
