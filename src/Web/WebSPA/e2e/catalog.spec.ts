import { test, expect } from '@playwright/test';

// Master prompt §6.6 journeys 1-2: browse/filter/paginate catalog, view item.
// The remaining journeys (sign-in, basket, checkout, orders, realtime updates,
// campaigns, logout) are added with the external IdP cutover slice.

test.describe('Catalog', () => {
  test('shows catalog items on the home page', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('esh-app')).toBeVisible();
    await expect(page.locator('.esh-catalog-items .esh-catalog-item').first()).toBeVisible();
  });

  test('filters catalog by brand and type', async ({ page }) => {
    await page.goto('/');
    const filters = page.locator('.esh-catalog-filter');
    await expect(filters).toHaveCount(2);

    await filters.nth(0).selectOption({ index: 1 });
    await filters.nth(1).selectOption({ index: 0 });
    await page.locator('.esh-catalog-send').click();

    await expect(page.locator('.esh-catalog-items')).toBeVisible();
  });

  test('paginates the catalog', async ({ page }) => {
    await page.goto('/');
    const next = page.locator('#Next').first();
    await expect(next).toBeVisible();
    await next.click();
    await expect(page.locator('.esh-pager-item--navigable').first()).toBeVisible();
  });

  test('shows item details (name, price, picture)', async ({ page }) => {
    await page.goto('/');
    const firstItem = page.locator('.esh-catalog-items .esh-catalog-item').first();
    await expect(firstItem.locator('.esh-catalog-name')).not.toBeEmpty();
    await expect(firstItem.locator('.esh-catalog-price')).toBeVisible();
    await expect(firstItem.locator('.esh-catalog-thumbnail')).toBeVisible();
  });
});
