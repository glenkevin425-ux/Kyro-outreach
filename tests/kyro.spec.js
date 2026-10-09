var { test, expect } = require('@playwright/test');

test.beforeEach(async function ({ page }) {
  await page.addInitScript(function () {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.goto('/');
});

test('all primary views render', async function ({ page }) {
  var views = [
    ['dashboard', 'Dashboard'], ['tasks', 'Tasks'], ['projects', 'Projects'],
    ['finance', 'Finance'], ['ideas', 'Ideas'], ['goals', 'Goals'], ['activity', 'Activity']
  ];
  for (var i = 0; i < views.length; i++) {
    await page.locator('[data-view="' + views[i][0] + '"]').first().click();
    await expect(page.locator('#title')).toHaveText(views[i][1]);
  }
});

test('modal traps keyboard focus and returns focus on close', async function ({ page }) {
  var trigger = page.locator('[data-action="open-form"][data-form="task"]').first();
  await trigger.click();
  await expect(page.locator('#f-title')).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(page.locator('#modal button[type="submit"]')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
});

test('task can be created, deleted, and restored with Undo', async function ({ page }) {
  await page.locator('[data-action="open-form"][data-form="task"]').first().click();
  await page.locator('#f-title').fill('Smoke test undo task');
  await page.locator('#f-due').selectOption('Today');
  await page.locator('#f-pri').selectOption('High');
  await page.locator('#modal button[type="submit"]').click();
  await page.locator('[data-view="tasks"]').first().click();

  var row = page.locator('.task-item[data-task-title="smoke test undo task"]');
  await expect(row).toBeVisible();
  await row.getByRole('button', {name:'Delete'}).click();
  await expect(row).toHaveCount(0);
  await page.locator('.toast-action', {hasText:'Undo'}).click();
  await expect(page.locator('.task-item[data-task-title="smoke test undo task"]')).toBeVisible();
});

test('finance allocation is preserved and expenses are searchable', async function ({ page }) {
  await page.locator('[data-view="finance"]').first().click();
  await expect(page.locator('#main')).toContainText('KSh 31,450');
  await expect(page.locator('#main')).toContainText('KSh 14,467');
  await expect(page.locator('#main')).toContainText('KSh 8,177');
  await expect(page.locator('#main')).toContainText('KSh 5,032');
  await expect(page.locator('#main')).toContainText('KSh 3,774');

  await page.locator('[data-action="open-form"][data-form="expense"]').click();
  await page.locator('#f-description').fill('Smoke test bus fare');
  await page.locator('#f-category').selectOption('transport');
  await page.locator('#f-amount').fill('350');
  await page.locator('#f-month').fill('2026-10');
  await page.locator('#modal button[type="submit"]').click();
  await expect(page.locator('#main')).toContainText('Smoke test bus fare');

  await page.locator('[data-action="palette"]').click();
  await page.locator('#pq').fill('Smoke test bus fare');
  await expect(page.locator('#pl')).toContainText('Expense · Smoke test bus fare');
});
