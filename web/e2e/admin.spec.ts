import { expect, test } from "@playwright/test";

// End-to-end admin flow (P24.5): secret gate -> navigate -> create format -> live preview renders.
// Requires the stack running (uvicorn serving /admin) and VIBE_PRINT_SECRET in env.
const SECRET = process.env.VIBE_PRINT_SECRET || "dev-secret";

test("unlock, navigate, author a format, and see a live preview", async ({ page }) => {
  await page.goto("/admin/");

  // Secret gate
  await page.getByPlaceholder("VIBE_PRINT_SECRET").fill(SECRET);
  await page.getByRole("button", { name: "Unlock" }).click();
  await expect(page.getByRole("heading", { name: "Printers", exact: true })).toBeVisible();

  // Navigate to Document Formats and create one
  await page.getByText("Document Formats").click();
  await page.getByRole("button", { name: "New format" }).click();

  // The server-rendered PNG preview appears (exercises API + render pipeline)
  await expect(page.locator("img.preview")).toBeVisible({ timeout: 10_000 });
});

test("PDF overlay editor renders a placed field (WYSIWYG)", async ({ page }) => {
  await page.goto("/admin/");
  await page.getByPlaceholder("VIBE_PRINT_SECRET").fill(SECRET);
  await page.getByRole("button", { name: "Unlock" }).click();
  await expect(page.getByRole("heading", { name: "Printers", exact: true })).toBeVisible();

  await page.getByText("PDF Overlays").click();
  await page.setInputFiles('input[type="file"]', "e2e/fixtures/base.pdf");

  // The base PDF renders to a canvas...
  await expect(page.locator("canvas")).toBeVisible({ timeout: 10_000 });
  // ...and adding a text field shows the resolved value in place on the page.
  await page.getByRole("button", { name: "+ Text" }).click();
  await expect(page.getByText("‹name›")).toBeVisible();
});

test("printer lifecycle: create, test, rename, delete-confirm", async ({ page }) => {
  await page.goto("/admin/");
  await page.getByPlaceholder("VIBE_PRINT_SECRET").fill(SECRET);
  await page.getByRole("button", { name: "Unlock" }).click();
  await expect(page.getByRole("heading", { name: "Printers", exact: true })).toBeVisible();

  // Unique names so the test is robust to any pre-existing rows.
  const name = `E2E ${Date.now()}`;
  const renamed = `${name} R`;

  // Create a virtual printer
  await page.getByLabel("Printer name").fill(name);
  await page.getByRole("button", { name: "Create" }).click();
  const row = page.locator("tr", { hasText: name });
  await expect(row).toBeVisible();

  // Test print → toast appears
  await row.getByRole("button", { name: "Test" }).click();
  await expect(page.getByText(/Test queued/)).toBeVisible({ timeout: 10_000 });

  // Rename via Edit
  await row.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Printer name").fill(renamed);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.locator("tr", { hasText: renamed })).toBeVisible();

  // Delete with confirmation dialog
  await page.locator("tr", { hasText: renamed }).getByRole("button", { name: "Delete" }).click();
  const dialog = page.locator(".card", { hasText: "Delete printer?" });
  await expect(dialog.getByRole("heading", { name: "Delete printer?" })).toBeVisible();
  await dialog.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.locator("tr", { hasText: renamed })).toHaveCount(0);
});

test("locking returns to the secret gate", async ({ page }) => {
  await page.goto("/admin/");
  await page.getByPlaceholder("VIBE_PRINT_SECRET").fill(SECRET);
  await page.getByRole("button", { name: "Unlock" }).click();
  await expect(page.getByRole("heading", { name: "Printers", exact: true })).toBeVisible();
  await page.getByText("Lock", { exact: true }).click();
  await expect(page.getByPlaceholder("VIBE_PRINT_SECRET")).toBeVisible();
});
