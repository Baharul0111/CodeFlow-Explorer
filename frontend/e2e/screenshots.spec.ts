/**
 * Captures the screenshots used in the README.
 *
 * Run with `pnpm screenshots`. It uses the deterministic mock client, so the wording in the boxes
 * is placeholder text — re-run against a real key for publishable images.
 */
import { mkdirSync } from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

const SAMPLE_ZIP = path.resolve(__dirname, "..", "..", "samples", "dist", "flask-todo.zip");
// Set LLM_MODE=anthropic plus ANTHROPIC_API_KEY to capture images with real Claude output.
const API_KEY = process.env.ANTHROPIC_API_KEY ?? "sk-ant-demo-0123456789";
const OUT = path.resolve(__dirname, "..", "..", "docs", "images");

test.use({ viewport: { width: 1420, height: 860 }, colorScheme: "dark" });

const GRAPH_VIEWPORT = { width: 1420, height: 620 };
test.describe.configure({ mode: "serial" });
// A real analysis takes a couple of minutes; the mock finishes in seconds.
test.setTimeout(420_000);

async function connect(page: Page): Promise<void> {
  await page.goto("/");
  await page.setInputFiles("#project-zip", SAMPLE_ZIP);
  await page.getByRole("button", { name: "Upload and scan" }).click();
  await page.getByLabel("Anthropic API key").fill(API_KEY);
  await page.getByRole("button", { name: "Test connection" }).click();
  await expect(page.getByText(/Connected\./)).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "What it will cost" })).toBeVisible();
  await expect(page.getByText(/\$\d+\.\d+ – \$\d+\.\d+/)).toBeVisible();
}

test("@screenshots capture the README images", async ({ page }) => {
  mkdirSync(OUT, { recursive: true });

  await connect(page);
  await page.screenshot({ path: path.join(OUT, "estimate.png") });

  await page.getByRole("button", { name: "Start analysis" }).click();
  const open = page.getByRole("link", { name: /Open the flow/ });
  await expect(open).toBeVisible({ timeout: 300_000 });
  // Wait for the whole run, not just level 0, so the exported page has depth to show.
  await expect(page.getByRole("heading", { name: "Your flow is ready" })).toBeVisible({
    timeout: 300_000,
  });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, "progress.png") });

  await open.click();
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  // A system flow is one wide row, so the graph shots use a shorter frame than the wizard ones.
  await page.setViewportSize(GRAPH_VIEWPORT);
  const fit = page.getByRole("button", { name: /fit view/i });
  await page.waitForTimeout(1200);
  await fit.click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT, "graph.png") });

  // Expanded, with a node selected so the side panel shows real code. No manual fit here: the
  // app zooms to the node that was opened, which is what keeps the text readable.
  await page.setViewportSize({ width: 1420, height: 860 });
  await page
    .getByRole("button", { name: /^Open up / })
    .first()
    .click();
  await page.waitForTimeout(1800);
  const inner = page.locator(".react-flow__node").filter({ hasText: "CHOICE" }).last();
  await inner.click();
  await page.waitForTimeout(900);
  await page.screenshot({
    path: path.join(OUT, "graph-expanded.png"),
    clip: { x: 0, y: 0, width: 1420, height: 700 },
  });

  // The shareable page, opened straight from disk with no server.
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Share as page" }).click();
  const file = await download;
  const saved = path.join(OUT, "..", "..", "frontend", "test-results", "shared-flow.html");
  await file.saveAs(saved);
  await page.goto(`file://${saved}`);
  await page.setViewportSize(GRAPH_VIEWPORT);
  await page.waitForTimeout(700);
  await page.getByRole("button", { name: "Open all" }).click();
  await page.waitForTimeout(900);
  const box = page.locator(".node").filter({ hasText: "CHOICE" }).last();
  await box.click();
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: "Fit" }).click();
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(OUT, "shared-page.png") });
});
