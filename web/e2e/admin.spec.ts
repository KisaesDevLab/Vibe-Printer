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

test("locking returns to the secret gate", async ({ page }) => {
  await page.goto("/admin/");
  await page.getByPlaceholder("VIBE_PRINT_SECRET").fill(SECRET);
  await page.getByRole("button", { name: "Unlock" }).click();
  await expect(page.getByRole("heading", { name: "Printers", exact: true })).toBeVisible();
  await page.getByText("Lock", { exact: true }).click();
  await expect(page.getByPlaceholder("VIBE_PRINT_SECRET")).toBeVisible();
});
