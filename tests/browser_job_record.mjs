// SPDX-FileCopyrightText: 2026 Bela Istvan MIHALIK
// SPDX-License-Identifier: Apache-2.0

// Optional browser regression: node tests/browser_job_record.mjs
// Requires Playwright JS and Chromium. No daemon, Ollama or user data is used.
const assert = (await import("node:assert/strict")).default;
const { readFile } = await import("node:fs/promises");
const { resolve } = await import("node:path");
const { fileURLToPath } = await import("node:url");
const { chromium } = await import("playwright");

export async function checkJobRecord() {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 850 } });
    const errors = [];
    page.on("pageerror", error => errors.push(String(error)));
    const root = new URL("../src/ragdbman/static/", import.meta.url);
    const initial = {
      id: "fixture-job", status: "running", current_item: "/fixtures/LICENSE",
      progress: { total: 30, processed: 1, completed: 1, unchanged: 0, failed: 0,
        skipped: 0, percent: 100/30, phase: "indexing" },
      timing: { elapsed_seconds: 1, estimated_remaining_seconds: 29 }
    };
    await page.route("http://ragdbman.test/**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.startsWith("/static/")) {
        const asset = path.slice("/static/".length);
        assert(["app.js", "style.css"].includes(asset));
        await route.fulfill({ body: await readFile(new URL(asset, root)),
          contentType: asset.endsWith(".js") ? "text/javascript" : "text/css" });
      } else if (path.startsWith("/api/")) {
        await route.fulfill({ json: initial });
      } else {
        await route.fulfill({ body: await readFile(new URL("index.html", root)), contentType: "text/html" });
      }
    });
    await page.addInitScript(() => {
      window.EventSource = class {
        constructor() { this.listeners = {}; window.testStream = this; }
        addEventListener(type, fn) { this.listeners[type] = fn; }
        close() {}
      };
    });
    await page.goto("http://ragdbman.test/collections/fixture/jobs/fixture-job");
    await page.locator("#job-status").waitFor();
    await page.locator("#job-inspection summary").click();
    await page.waitForFunction(() => document.querySelector("#job-inspection").open);
    const record = page.locator("#job-record");
    await record.scrollIntoViewIfNeeded();
    await page.evaluate(() => { window.originalRecord = document.querySelector("#job-record"); });
    const snapshot = await record.textContent();
    // Genuine mouse selection, not merely an assertion about unchanged text.
    const box = await record.boundingBox();
    await page.mouse.move(box.x + 25, box.y + 35);
    await page.mouse.down();
    await page.mouse.move(box.x + 240, box.y + 78, { steps: 12 });
    await page.mouse.up();
    const selected = await page.evaluate(() => getSelection().toString());
    assert(selected.length > 0, "Mouse must select record text");
    const update = async (processed, status = "running") => {
      const job = structuredClone(initial);
      job.status = status;
      Object.assign(job.progress, { processed, completed: processed, percent: processed / 30 * 100,
        phase: status === "running" ? "indexing" : "finished" });
      job.timing.elapsed_seconds = processed;
      job.timing.estimated_remaining_seconds = 30 - processed;
      await page.evaluate(j => window.testStream.listeners.progress({ data: JSON.stringify(j) }), job);
    };
    for (let n = 2; n <= 10; n++) await update(n);
    assert(await page.locator("#job-inspection").evaluate(e => e.open));
    assert.equal(await record.textContent(), snapshot);
    assert.equal(await page.evaluate(() => getSelection().toString()), selected);
    assert(await record.evaluate(e => e === window.originalRecord));
    assert.match(await page.locator("#job-progress-summary").textContent(), /10 \/ 30/);
    assert.equal(await page.locator("#job-elapsed").textContent(), "10s");
    await page.locator("#refresh-job-record").focus();
    await update(11);
    assert.equal(await page.evaluate(() => document.activeElement.id), "refresh-job-record");
    await page.locator("#refresh-job-record").click();
    assert.equal(JSON.parse(await record.textContent()).progress.processed, 11);
    assert(await page.locator("#job-inspection").evaluate(e => e.open));
    await update(30, "completed");
    assert.equal(JSON.parse(await record.textContent()).progress.processed, 11);
    assert(await page.locator("#cancel").isDisabled());
    await page.locator("#job-inspection summary").click();
    await page.waitForFunction(() => !document.querySelector("#job-inspection").open);
    await page.locator("#job-inspection summary").click();
    await page.waitForFunction(() => JSON.parse(document.querySelector("#job-record").textContent).status === "completed");
    await page.setViewportSize({ width: 375, height: 812 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    return "Selection, expansion, node identity, focus, refresh/reopen and live counters passed.";
  } finally {
    await browser.close();
  }
}

if (typeof process !== "undefined" && process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  console.log(await checkJobRecord());
}
