import { readFileSync } from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

const SAMPLE_ZIP = path.resolve(__dirname, "..", "..", "samples", "dist", "flask-todo.zip");

test.describe.configure({ mode: "serial" });

/** Upload → connect → estimate → analyse, ending on the graph screen. */
async function runAnalysis(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "CodeFlow Explorer" })).toBeVisible();

  await page.setInputFiles("#project-zip", SAMPLE_ZIP);
  await expect(page.getByText("flask-todo.zip")).toBeVisible();
  await page.getByRole("button", { name: "Upload and scan" }).click();

  // Connect: the model list is served by the API, the key never leaves the server.
  await expect(page.getByLabel("Anthropic API key")).toBeVisible();
  await page.getByLabel("Anthropic API key").fill("sk-ant-e2e-0123456789");
  await page.getByRole("button", { name: "Test connection" }).click();
  await expect(page.getByText(/Connected\. \d+ models available/)).toBeVisible();
  await expect(page.locator("#model")).toContainText("Mock Capable");
  await page.getByRole("button", { name: "Continue" }).click();

  // Estimate: a real cost range, then start.
  await expect(page.getByRole("heading", { name: "What it will cost" })).toBeVisible();
  await expect(page.getByText(/\$\d+\.\d+ – \$\d+\.\d+/)).toBeVisible();
  await page.getByRole("button", { name: "Start analysis" }).click();

  // Progress: live stages, then the graph link.
  await expect(
    page.getByRole("heading", { name: /Your flow is ready|Reading your project/ }),
  ).toBeVisible();
  const openLink = page.getByRole("link", { name: /Open the flow/ });
  await expect(openLink).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("Spend so far")).toBeVisible();
  await openLink.click();
  await expect(page).toHaveURL(/\/projects\/[a-f0-9]+\/graph/);
}

test("upload, analyse, then drill from the system flow down to a leaf", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await runAnalysis(page);

  // The top level has a start node and an output node, and every edge is labelled.
  const canvas = page.locator(".react-flow");
  await expect(canvas).toBeVisible();
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  await expect(page.getByText("START").first()).toBeVisible();
  await expect(page.getByText("OUTPUT").first()).toBeVisible();
  const edgeLabels = page.locator(".react-flow__edge-text");
  await expect(edgeLabels.first()).toBeVisible();
  expect(await edgeLabels.count()).toBeGreaterThan(0);
  // SVG <text> has no innerText, so read text content.
  for (const label of await edgeLabels.allTextContents()) {
    expect((label ?? "").trim().length).toBeGreaterThan(0);
    expect((label ?? "").trim().toLowerCase()).not.toBe("data");
  }

  const nodeCountBefore = await page.locator(".react-flow__node").count();
  expect(nodeCountBefore).toBeGreaterThanOrEqual(3);

  // Clicking a node opens the side panel with a real file and line range.
  await page.locator(".react-flow__node").first().click();
  const panel = page.getByRole("complementary", { name: "Details" });
  await expect(panel).toBeVisible();
  await expect(panel.getByText("Where this lives in the code")).toBeVisible();
  const reference = await panel.locator("li.font-mono").first().innerText();
  expect(reference).toMatch(/\.(py|md|txt)/);
  expect(reference).toMatch(/:\d+/);

  // Expanding a node adds children inside it.
  const expander = page.getByRole("button", { name: /^Open up / }).first();
  await expander.click();
  await expect
    .poll(async () => page.locator(".react-flow__node").count(), { timeout: 60_000 })
    .toBeGreaterThan(nodeCountBefore);

  // Keep drilling until a leaf appears — a node with line-level code and nothing inside it.
  const fitView = page.getByRole("button", { name: /fit view/i });
  let reachedLeaf = false;
  for (let depth = 0; depth < 6 && !reachedLeaf; depth += 1) {
    await fitView.click();
    await page.waitForTimeout(600);

    // A leaf is a node card with no "Open up" button.
    const cards = page.locator(".react-flow__node");
    const total = await cards.count();
    for (let index = 0; index < total; index += 1) {
      const card = cards.nth(index);
      if ((await card.getByRole("button", { name: /^Open up / }).count()) > 0) continue;
      const box = await card.boundingBox();
      if (!box || box.y < 0 || box.x < 0) continue;
      await card.click();
      const details = page.getByRole("complementary", { name: "Details" });
      await expect(details).toBeVisible();
      if ((await details.innerText()).includes("This is the smallest step")) {
        const ref = await details.locator("li.font-mono").first().innerText();
        expect(ref).toMatch(/:\d+/);
        reachedLeaf = true;
        break;
      }
    }
    if (reachedLeaf) break;

    const expanders = page.getByRole("button", { name: /^Open up / });
    const expandable = await expanders.count();
    if (expandable === 0) break;
    await expanders.nth(expandable - 1).click();
    await page.waitForTimeout(1500);
  }
  expect(reachedLeaf, "drilling down should reach a leaf with line-level code").toBe(true);

  const realErrors = consoleErrors.filter(
    (text) => !text.includes("favicon") && !text.includes("Download the React DevTools"),
  );
  expect(realErrors, `console errors: ${realErrors.join(" | ")}`).toHaveLength(0);
});

test("search jumps to a node, and the graph can be exported", async ({ page }) => {
  await page.goto("/projects");
  await page.getByRole("link", { name: "flask-todo" }).first().click();
  await expect(page.locator(".react-flow__node").first()).toBeVisible();

  await page.getByLabel("Search the flow").fill("auth");
  const hit = page.getByRole("button", { name: /Sort app|auth/ }).first();
  await expect(hit).toBeVisible({ timeout: 15_000 });

  const jsonDownload = page.waitForEvent("download");
  await page.getByRole("link", { name: "JSON" }).click();
  expect((await jsonDownload).suggestedFilename()).toContain("graph.json");
});

test("the graph can be shared as a link and as a self-contained page", async ({ page }) => {
  await page.goto("/projects");
  await page.getByRole("link", { name: "flask-todo" }).first().click();
  await expect(page.locator(".react-flow__node").first()).toBeVisible();

  // A link anyone with access to this server can open.
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByRole("button", { name: "Copy link" }).click();
  await expect(page.getByRole("button", { name: "Link copied" })).toBeVisible();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toMatch(/\/projects\/[a-f0-9]+\/graph$/);

  // A single file that opens and expands anywhere, with no server at all.
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Share as page" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toContain("flow.html");
  const stream = await file.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(chunk as Buffer);
  const html = Buffer.concat(chunks).toString("utf8");
  expect(html).toContain("<title>");
  expect(html).toContain("function layout");
  expect(html).not.toContain('src="http');
  const data = JSON.parse(html.match(/type="application\/json">([\s\S]*?)<\/script>/)?.[1] ?? "{}");
  expect(data.nodes.length).toBeGreaterThan(3);
  expect(Object.keys(data.snippets).length).toBeGreaterThan(0);
});

test("reopening a finished project costs nothing", async ({ page, request }) => {
  await page.goto("/projects");
  const firstProject = page.getByRole("link", { name: "flask-todo" }).first();
  await firstProject.click();
  await expect(page).toHaveURL(/\/projects\/([a-f0-9]+)\/graph/);
  const projectId = page.url().match(/projects\/([a-f0-9]+)\/graph/)?.[1];
  expect(projectId).toBeTruthy();

  const before = await (
    await request.get(`http://localhost:8010/api/projects/${projectId}/analysis/usage`)
  ).json();
  await page.reload();
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  const after = await (
    await request.get(`http://localhost:8010/api/projects/${projectId}/analysis/usage`)
  ).json();
  expect(after.calls).toBe(before.calls);
  expect(after.cost_usd).toBe(before.cost_usd);
});

test("a malicious zip is refused with a plain message", async ({ page }) => {
  await page.goto("/");
  // A zip whose entry escapes the extraction folder.
  const zipSlip = buildZipSlip();
  await page.setInputFiles("#project-zip", {
    name: "evil.zip",
    mimeType: "application/zip",
    buffer: zipSlip,
  });
  await page.getByRole("button", { name: "Upload and scan" }).click();
  // Next renders its own empty route announcer with role="alert"; match ours by content.
  await expect(page.getByRole("alert").filter({ hasText: /unsafe path/i })).toBeVisible();
});

/** Minimal stored (uncompressed) zip containing one `../../evil.py` entry. */
function buildZipSlip(): Buffer {
  const name = Buffer.from("../../evil.py");
  const content = Buffer.from("print('nope')\n");
  const crc = crc32(content);

  const local = Buffer.alloc(30);
  local.writeUInt32LE(0x04034b50, 0);
  local.writeUInt16LE(20, 4);
  local.writeUInt16LE(0, 6);
  local.writeUInt16LE(0, 8);
  local.writeUInt16LE(0, 10);
  local.writeUInt16LE(0, 12);
  local.writeUInt32LE(crc, 14);
  local.writeUInt32LE(content.length, 18);
  local.writeUInt32LE(content.length, 22);
  local.writeUInt16LE(name.length, 26);
  local.writeUInt16LE(0, 28);

  const central = Buffer.alloc(46);
  central.writeUInt32LE(0x02014b50, 0);
  central.writeUInt16LE(20, 4);
  central.writeUInt16LE(20, 6);
  central.writeUInt16LE(0, 8);
  central.writeUInt16LE(0, 10);
  central.writeUInt16LE(0, 12);
  central.writeUInt16LE(0, 14);
  central.writeUInt32LE(crc, 16);
  central.writeUInt32LE(content.length, 20);
  central.writeUInt32LE(content.length, 24);
  central.writeUInt16LE(name.length, 28);
  central.writeUInt16LE(0, 30);
  central.writeUInt16LE(0, 32);
  central.writeUInt16LE(0, 34);
  central.writeUInt16LE(0, 36);
  central.writeUInt32LE(0, 38);
  central.writeUInt32LE(0, 42);

  const localBlock = Buffer.concat([local, name, content]);
  const centralBlock = Buffer.concat([central, name]);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(1, 8);
  end.writeUInt16LE(1, 10);
  end.writeUInt32LE(centralBlock.length, 12);
  end.writeUInt32LE(localBlock.length, 16);
  end.writeUInt16LE(0, 20);
  return Buffer.concat([localBlock, centralBlock, end]);
}

function crc32(buffer: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

test("the sample zip exists so the suite is self-contained", () => {
  expect(readFileSync(SAMPLE_ZIP).length).toBeGreaterThan(100);
});
