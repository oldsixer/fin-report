#!/usr/bin/env node
/* Browser acceptance test for the live TCEG frontend. Requires the playwright package. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const baseUrl = process.argv[2] || "http://127.0.0.1:8765";
const screenshotDir = path.resolve(
  process.argv[3] || "experiments/research_report_tceg_jiangbolong/visualization/screenshots",
);
const executablePath = process.env.TCEG_CHROMIUM_PATH;
const pages = [
  "direction-1-workbench.html",
  "direction-2-atlas.html",
  "direction-3-ledger.html",
];
const viewports = [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

(async () => {
  fs.mkdirSync(screenshotDir, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath });
  const results = [];

  for (const pageName of pages) {
    for (const viewport of viewports) {
      const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
      const page = await context.newPage();
      const consoleErrors = [];
      const pageErrors = [];
      page.on("console", (message) => {
        if (["error", "warning"].includes(message.type())) consoleErrors.push(`${message.type()}: ${message.text()}`);
      });
      page.on("pageerror", (error) => pageErrors.push(String(error)));

      const response = await page.goto(`${baseUrl}/${pageName}`, { waitUntil: "networkidle" });
      assert(response && response.ok(), `${pageName}: HTTP load failed`);
      await page.waitForFunction(() => Boolean(window.TCEG_VIEWER));
      await page.waitForTimeout(350);

      const initialState = await page.evaluate(() => window.TCEG_VIEWER.getState());
      assert(initialState.currentMode === "thesis", `${pageName}: default mode is not thesis`);
      assert(initialState.renderedNodes > 0, `${pageName}: no thesis nodes rendered`);
      assert((await page.locator("#reportSubtitle").innerText()).includes("LIVE API"), `${pageName}: live API data was not used`);

      const screenshotName = `${path.parse(pageName).name}-${viewport.width}x${viewport.height}.png`;
      await page.screenshot({ path: path.join(screenshotDir, screenshotName), fullPage: false });

      await page.locator('[data-mode="data"]').click();
      const dataState = await page.evaluate(() => window.TCEG_VIEWER.getState());
      assert(dataState.currentMode === "data" && dataState.renderedNodes > 0, `${pageName}: data mode failed`);

      await page.locator('[data-mode="full"]').click();
      const fullState = await page.evaluate(() => window.TCEG_VIEWER.getState());
      assert(fullState.currentMode === "full", `${pageName}: full mode failed`);
      assert(fullState.renderedNodes === 854, `${pageName}: expected 854 full nodes, got ${fullState.renderedNodes}`);

      await page.locator("#searchInput").fill("Micron宣布上调");
      await page.locator("#searchResults [data-node-id]").first().click();
      const selectedState = await page.evaluate(() => window.TCEG_VIEWER.getState());
      assert(selectedState.selectedNodeId, `${pageName}: search did not select a node`);
      assert(await page.locator("#inspector .evidence-card").count(), `${pageName}: selected node has no visible evidence`);

      await page.locator("#nextPage").click();
      assert((await page.locator("#pageIndicator").innerText()).startsWith("2"), `${pageName}: report paging failed`);

      assert(pageErrors.length === 0, `${pageName}: page errors: ${pageErrors.join(" | ")}`);
      assert(consoleErrors.length === 0, `${pageName}: console errors: ${consoleErrors.join(" | ")}`);
      results.push({ page: pageName, viewport: `${viewport.width}x${viewport.height}`, initialState, status: "PASS" });
      await context.close();
    }
  }

  await browser.close();
  const report = { status: "PASS", results };
  fs.writeFileSync(
    path.join(path.dirname(screenshotDir), "acceptance_test.json"),
    `${JSON.stringify(report, null, 2)}\n`,
    "utf8",
  );
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
})().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
