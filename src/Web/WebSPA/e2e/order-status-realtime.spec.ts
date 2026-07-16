import { test, expect } from '@playwright/test';

// Master prompt §6.6 journey 7: observe order-status realtime updates.
// Requires the full compose stack (identity-api, ordering-api,
// ordering-signalrhub, webspa) plus demo credentials. Skipped unless
// E2E_USER/E2E_PASSWORD are set (defaults match the seeded demo user).
//
// Journey: sign in -> place an order from the basket -> the Socket.IO hub
// (ordering-signalrhub at /hub/notificationhub) pushes UpdatedOrderState as
// the order advances (submitted -> awaitingvalidation -> ...), surfaced as a
// toastr notification with 'Updated to status: <status>' / 'Order Id: <id>'.

const user = process.env.E2E_USER;
const password = process.env.E2E_PASSWORD;

test.describe('Order status realtime updates', () => {
  test.skip(!user || !password, 'Set E2E_USER and E2E_PASSWORD to run the realtime journey');

  test('receives an UpdatedOrderState notification after checkout', async ({ page }) => {
    await page.goto('/');

    // Sign in through the IdP login page.
    await page.locator('.esh-identity-name').click();
    await page.getByText('Login', { exact: true }).click();
    await page.locator('input[name="Username"], input[name="username"]').fill(user!);
    await page.locator('input[name="Password"], input[name="password"]').fill(password!);
    await page.locator('button[type="submit"], button[value="login"]').first().click();
    await page.waitForURL('**/catalog**');

    // Add an item and check out.
    await page.locator('.esh-catalog-item input[type="button"], .esh-catalog-item .esh-catalog-button').first().click();
    await page.locator('.esh-basketstatus').click();
    await page.getByText('Checkout', { exact: false }).click();
    await page.locator('button', { hasText: /Place Order/i }).click();

    // The hub pushes the first status transition within the grace period.
    const toast = page.locator('.toast-success, .overlay-container .toast');
    await expect(toast.filter({ hasText: /Updated to status/i }).first())
      .toBeVisible({ timeout: 120_000 });
    await expect(toast.filter({ hasText: /Order Id/i }).first()).toBeVisible();
  });
});
