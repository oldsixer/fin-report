#!/usr/bin/env node

const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { chromium } = require("playwright");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

(async () => {
  const root = path.resolve(process.argv[2] || "deliverables/TCEG_Workbench_Portable");
  const executablePath = process.env.TCEG_CHROMIUM_PATH;
  const browser = await chromium.launch({ headless: true, executablePath });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  const consoleErrors = [];
  const remoteRequests = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) consoleErrors.push(`${message.type()}: ${message.text()}`);
  });
  page.on("request", (request) => {
    if (/^https?:/i.test(request.url())) remoteRequests.push(request.url());
  });

  await page.goto(pathToFileURL(path.join(root, "index.html")).href, { waitUntil: "networkidle" });
  assert((await page.locator("#nodeStat").innerText()) === "854", "node count did not load");
  assert((await page.locator("#edgeStat").innerText()).replace(/,/g, "") === "2509", "edge count did not load");
  assert(await page.locator("#graphSvg .node").count() > 0, "graph did not render");
  assert(await page.locator("#reportImage").evaluate((image) => image.complete && image.naturalWidth > 0), "report image did not load");
  const pdfHref = await page.locator("#pdfLink").getAttribute("href");
  assert(pdfHref === "assets/source-report.pdf", `unexpected PDF path: ${pdfHref}`);
  await page.locator('[data-mode="data"]').click();
  assert(await page.locator("#graphSvg .node").count() > 0, "data mode did not render");
  await page.locator('[data-mode="full"]').click();
  assert(await page.locator("#graphSvg .node").count() === 854, "full mode does not contain all graph nodes");
  assert(pageErrors.length === 0, `page errors: ${pageErrors.join(" | ")}`);
  assert(consoleErrors.length === 0, `console errors: ${consoleErrors.join(" | ")}`);
  assert(remoteRequests.length === 0, `unexpected remote requests: ${remoteRequests.join(" | ")}`);

  await browser.close();
  process.stdout.write("PASS: portable workbench opens from file:// with 854 nodes, local assets, and zero remote requests.\n");
})().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
