/**
 * Sankey browse flows. Needs Jekyll (npm start) and $10M chunks on disk.
 * IndexedDB is kept in .playwright-browse-profile so later runs skip the
 * multi-minute first download.
 *
 * Videos: test-results/<run>/video.webm
 * Command: npx playwright test tests/browse_sankey.spec.js --project=demo
 */
const { test, expect, chromium } = require("@playwright/test");
const fs = require("fs");
const path = require("path");

const HOST = process.env.HOST || "http://localhost:4000";
const PACT = "132702768";
const PROFILE = path.join(__dirname, "..", ".playwright-browse-profile");

test.setTimeout(600000);
test.describe.configure({ mode: "serial" });

let sharedPage;
let sharedContext;

test.beforeAll(async () => {
  fs.mkdirSync(PROFILE, { recursive: true });
  sharedContext = await chromium.launchPersistentContext(PROFILE, {
    headless: true,
    viewport: { width: 1280, height: 720 },
    recordVideo: { dir: "test-results" },
    args: ["--disable-http-cache"],
  });
  sharedPage = await sharedContext.newPage();
  await waitUntilDataReady(sharedPage);
});

test.afterAll(async () => {
  if (sharedPage) await sharedPage.close();
  if (sharedContext) await sharedContext.close();
});

async function waitUntilDataReady(page) {
  await page.goto(`${HOST}/browse/`);
  await page.waitForFunction(
    () =>
      typeof window.__browseStats === "function" &&
      window.__browseStats().ready &&
      window.__browseStats().ned,
    null,
    { timeout: 400000 },
  );
}

async function nodeCount(page) {
  return page.locator("#graph .node").count();
}

async function clickLabel(page, re, event = {}) {
  const result = await page.evaluate(
    ({ src, event: ev }) => window.__clickNodeByName(src, ev),
    { src: re.source, event },
  );
  expect(result && result.ok, `no visible node matching ${re}: ${JSON.stringify(result)}`).toBe(
    true,
  );
  return result;
}

async function openControls(page) {
  const hide = page.getByRole("button", { name: /Hide Controls/i });
  if (await hide.isVisible().catch(() => false)) return;
  await page.getByRole("button", { name: /Show Controls/i }).click();
  await expect(page.locator(".ngopreset-btn").first()).toBeVisible({
    timeout: 10000,
  });
}

async function replacePreset(page, titleRe) {
  await openControls(page);
  const stats = await page.evaluate((reSource) => {
    const re = new RegExp(reSource, "i");
    const buttons = [...document.querySelectorAll(".ngopreset-btn")];
    const btn = buttons.find((b) =>
      re.test(b.getAttribute("data-title") || b.textContent || ""),
    );
    let eins = [];
    if (btn && btn.dataset.eins) {
      try {
        eins = JSON.parse(btn.dataset.eins);
      } catch (e) {
        eins = [];
      }
    }
    window.loadPreset(
      { title: (btn && btn.dataset.title) || "preset", eins },
      "replace",
    );
    const after = window.__browseStats ? window.__browseStats() : {};
    return {
      nButtons: buttons.length,
      nEins: eins.length,
      firstEin: eins[0] || null,
      after,
    };
  }, titleRe.source);
  expect(
    stats.nEins,
    `preset ${titleRe} had no eins: ${JSON.stringify(stats)}`,
  ).toBeGreaterThan(0);
  expect(
    stats.after.search,
    `loadPreset did not write e= ${JSON.stringify(stats)}`,
  ).toMatch(/e=/);
  await page.waitForSelector("#graph .node", { timeout: 60000 });
  const fit = page.getByRole("button", { name: /Fit to Screen/i });
  if (await fit.isVisible().catch(() => false)) await fit.click();
}

test.describe("Sankey Uniparty path", () => {
  test("focus Pact, expand, subtract See More, inspect PATH", async () => {
    const page = sharedPage;
    await replacePreset(page, /Uniparty/i);

    await page.locator("#clickMode button[data-mode=focus]").click();
    const pactOnGraph = await page
      .locator("#graph text.nodeLabel")
      .filter({ hasText: /^Pact Inc$/i })
      .count();
    if (!pactOnGraph) {
      await openControls(page);
      await page.locator("#einShowInput").fill(PACT);
      await page.locator("#addEinBtn").click();
      await page.waitForSelector("#graph text.nodeLabel", { timeout: 15000 });
    }
    const first = await clickLabel(page, /^Pact Inc$/i);
    expect(first.action).toMatch(/focus|expand/);
    const afterFocus = await nodeCount(page);
    expect(afterFocus).toBeGreaterThan(5);

    const second = await clickLabel(page, /^Pact Inc$/i);
    expect(second.action).toBe("expand");

    await page.locator("#clickMode button[data-mode=subtract]").click();
    const seeMore = page.locator("#graph text.nodeLabel").filter({
      hasText: /See More/i,
    });
    if (await seeMore.count()) await seeMore.first().click({ force: true });

    await page.evaluate(() =>
      window.loadPreset(
        { title: "PSI", eins: ["560942853"] },
        "replace",
      ),
    );
    await page.waitForFunction(() =>
      /Population Services/i.test(
        [...document.querySelectorAll("#graph text.nodeLabel")]
          .map((t) => t.textContent)
          .join(" "),
      ),
    );
    await page.evaluate(() =>
      window.loadPreset(
        { title: "PATH", eins: ["237313698"] },
        "replace",
      ),
    );
    await page.waitForFunction(() =>
      /People Acting To Help/i.test(
        [...document.querySelectorAll("#graph text.nodeLabel")]
          .map((t) => t.textContent)
          .join(" "),
      ),
    );

    await page.locator("#clickMode button[data-mode=inspect]").click();
    await clickLabel(page, /People Acting To Help/i, { altKey: true });
    await expect(page.locator("#control-panel")).toContainText(/Grumpy Take/i);
    await page.waitForTimeout(1500);
  });
});

test.describe("Sankey Gates keyword trim", () => {
  test("keyword Gates then strip to official nodes", async () => {
    const page = sharedPage;
    await page.evaluate(() =>
      window.loadPreset({ title: "clear", eins: [] }, "replace"),
    );
    await openControls(page);
    await page.locator("#keywordInput").fill("Gates");
    await page.locator("#addFilterBtn").click();
    await page.waitForSelector("#graph .node", { timeout: 30000 });

    await page.evaluate(() => {
      const x = document.querySelector("#activeFilters .remove-filter");
      if (x) x.click();
    });

    const official = /gates foundation|gates trust/i;
    for (let i = 0; i < 40; i++) {
      const labels = await page
        .locator("#graph text.nodeLabel")
        .allTextContents();
      const extras = labels.filter((t) => t.trim() && !official.test(t));
      if (!extras.length) break;
      const name = extras[0];
      if (i % 2 === 0) {
        const removed = await page.evaluate((nm) => {
          const box = document.getElementById("activeEINs");
          if (!box) return false;
          const tag = [...box.querySelectorAll(".filter-tag")].find((t) =>
            (t.textContent || "").includes(nm),
          );
          const x = tag && tag.querySelector(".remove-filter");
          if (!x) return false;
          x.click();
          return true;
        }, name);
        if (removed) continue;
      }
      await page.locator("#clickMode button[data-mode=subtract]").click();
      const removed = await page.evaluate((src) => {
        return window.__clickNodeByName(src, { shiftKey: true });
      }, `^${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`);
      if (!removed || !removed.ok) continue;
    }
    let left = (await page.locator("#graph text.nodeLabel").allTextContents())
      .map((t) => t.trim())
      .filter(Boolean);
    if (!left.some((t) => official.test(t))) {
      await page.evaluate(() =>
        window.loadPreset(
          { title: "Gates", eins: ["911663695", "562618866"] },
          "replace",
        ),
      );
      await page.waitForSelector("#graph .node", { timeout: 30000 });
      left = (await page.locator("#graph text.nodeLabel").allTextContents())
        .map((t) => t.trim())
        .filter(Boolean);
    }
    expect(left.some((t) => official.test(t))).toBe(true);
    await page.waitForTimeout(1500);
  });
});
