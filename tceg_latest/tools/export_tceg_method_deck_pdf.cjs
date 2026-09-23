#!/usr/bin/env node

const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');

async function main() {
  const slidesDir = path.resolve(process.argv[2] || '');
  const outputFile = path.resolve(process.argv[3] || '');
  if (!process.argv[2] || !process.argv[3]) {
    throw new Error('usage: node export_tceg_method_deck_pdf.cjs <slides-dir> <output.pdf>');
  }

  const slides = (await fs.readdir(slidesDir))
    .filter((name) => /^\d{2}-.+\.html$/.test(name))
    .sort();
  if (slides.length === 0) throw new Error(`no slide HTML files in ${slidesDir}`);

  await fs.mkdir(path.dirname(outputFile), { recursive: true });
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'tceg-method-deck-'));
  const chromiumPath = process.env.TCEG_CHROMIUM_PATH || undefined;
  const browser = await chromium.launch({
    executablePath: chromiumPath,
    headless: true,
  });

  const pageFiles = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
    for (const [index, slide] of slides.entries()) {
      const page = await context.newPage();
      await page.goto(pathToFileURL(path.join(slidesDir, slide)).href, { waitUntil: 'networkidle' });
      await page.emulateMedia({ media: 'screen' });
      await page.evaluate(async () => document.fonts.ready);
      const pageFile = path.join(tempDir, `${String(index + 1).padStart(2, '0')}.pdf`);
      await page.pdf({
        path: pageFile,
        width: '1920px',
        height: '1080px',
        printBackground: true,
        margin: { top: 0, right: 0, bottom: 0, left: 0 },
      });
      pageFiles.push(pageFile);
      await page.close();
      process.stdout.write(`[${index + 1}/${slides.length}] ${slide}\n`);
    }
  } finally {
    await browser.close();
  }

  const merged = spawnSync('pdfunite', [...pageFiles, outputFile], { encoding: 'utf8' });
  await fs.rm(tempDir, { recursive: true, force: true });
  if (merged.status !== 0) {
    throw new Error(merged.stderr || `pdfunite exited with ${merged.status}`);
  }
  process.stdout.write(`wrote ${outputFile} (${slides.length} pages)\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
