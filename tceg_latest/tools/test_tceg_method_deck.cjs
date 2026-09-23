#!/usr/bin/env node
/* Browser acceptance test for the TCEG extraction-method deck. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const baseUrl = process.argv[2] || "http://127.0.0.1:8765/method-deck";
const outputDir = path.resolve(
  process.argv[3] || "experiments/research_report_tceg_jiangbolong/visualization/method-deck/screenshots",
);
const executablePath = process.env.TCEG_CHROMIUM_PATH;
const slides = [
  "01-cover.html",
  "02-thesis-contract.html",
  "03-00-schema-envelope.html",
  "03-01-schema-semantics.html",
  "03-02-schema-edges-audit.html",
  "03-pipeline.html",
  "04-source-layer.html",
  "05-hybrid-extraction.html",
  "06-ontology-numbers.html",
  "07-evidence-gate.html",
  "08-relations-reasoning.html",
  "09-output-validation.html",
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

(async () => {
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath });
  const results = [];

  for (const slide of slides) {
    const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
    const page = await context.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    page.on("console", (message) => {
      if (["error", "warning"].includes(message.type())) consoleErrors.push(`${message.type()}: ${message.text()}`);
    });
    page.on("pageerror", (error) => pageErrors.push(String(error)));
    const response = await page.goto(`${baseUrl}/slides/${slide}`, { waitUntil: "networkidle" });
    assert(response && response.ok(), `${slide}: HTTP load failed`);
    const dimensions = await page.evaluate(() => ({
      bodyWidth: document.body.scrollWidth,
      bodyHeight: document.body.scrollHeight,
      htmlWidth: document.documentElement.scrollWidth,
      htmlHeight: document.documentElement.scrollHeight,
      images: [...document.images].map((image) => ({ src: image.src, complete: image.complete, width: image.naturalWidth })),
    }));
    assert(dimensions.bodyWidth <= 1920 && dimensions.htmlWidth <= 1920, `${slide}: horizontal overflow ${JSON.stringify(dimensions)}`);
    assert(dimensions.bodyHeight <= 1080 && dimensions.htmlHeight <= 1080, `${slide}: vertical overflow ${JSON.stringify(dimensions)}`);
    assert(dimensions.images.every((image) => image.complete && image.width > 0), `${slide}: broken image ${JSON.stringify(dimensions.images)}`);
    assert(pageErrors.length === 0, `${slide}: page errors ${pageErrors.join(" | ")}`);
    assert(consoleErrors.length === 0, `${slide}: console errors ${consoleErrors.join(" | ")}`);
    await page.screenshot({ path: path.join(outputDir, slide.replace(".html", ".png")), fullPage: false });
    results.push({ slide, dimensions, status: "PASS" });
    await context.close();
  }

  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const indexErrors = [];
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) indexErrors.push(`${message.type()}: ${message.text()}`);
  });
  await page.goto(`${baseUrl}/index.html?ov=grid`, { waitUntil: "networkidle" });
  assert(await page.locator("#wall .card").count() === slides.length, "index: overview slide count mismatch");
  await page.screenshot({ path: path.join(outputDir, "00-overview.png"), fullPage: false });
  await page.locator("#startBtn").click();
  await page.waitForTimeout(250);
  assert((await page.locator("#counter").innerText()).startsWith(`1 / ${slides.length}`), "index: presentation did not start at slide 1");
  await page.keyboard.press("ArrowRight");
  assert((await page.locator("#counter").innerText()).startsWith(`2 / ${slides.length}`), "index: ArrowRight navigation failed");
  await page.keyboard.press("End");
  assert((await page.locator("#counter").innerText()).startsWith(`${slides.length} / ${slides.length}`), "index: End navigation failed");
  await page.keyboard.press("Escape");
  assert(await page.locator("body").getAttribute("data-mode") === "overview", "index: Escape did not return to overview");
  assert(indexErrors.length === 0, `index: console errors ${indexErrors.join(" | ")}`);
  await context.close();
  await browser.close();

  const report = { status: "PASS", slide_count: slides.length, results, index_navigation: "PASS" };
  const reportPath = path.join(path.dirname(outputDir), "acceptance_test.json");
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
})().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
