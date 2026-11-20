const { test, expect } = require("@playwright/test");

const HOST = process.env.HOST || "http://localhost:4000";

async function openBuilder(page) {
  await page.goto(HOST + "/sankeybuilder/", { waitUntil: "load" });
  await page.evaluate(
    () =>
      new Promise((res) => {
        const r = indexedDB.deleteDatabase("sankeybuilder");
        r.onsuccess = r.onerror = r.onblocked = () => res();
      }),
  );
  await page.reload({ waitUntil: "load" });
  await page.getByRole("button", { name: "New" }).click();
  await page.waitForSelector("#sb-node-form");
}

test.describe("Show Don't Tell", () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test("boots, adds an org, and keeps variables off :root", async ({ page }) => {
    await openBuilder(page);

    const leaked = await page.evaluate(() => {
      const root = getComputedStyle(document.documentElement);
      return ["--bg", "--panel", "--ink"].filter(
        (v) => root.getPropertyValue(v).trim() !== "",
      );
    });
    expect(leaked).toEqual([]);

    await page.locator('#sb-node-form input[name="name"]').fill("Alpha Fund");
    await page.locator('#sb-node-form button[type="submit"]').click();
    await expect(page.locator("#sb-status")).toContainText("1 of 1 nodes");
    await expect(page.locator("#sb-svg g.sb-node")).toHaveCount(1);
    await expect(page.locator("#sb-new")).toHaveText("Clear");
    await expect(page.locator("#sb-save-svg")).toBeVisible();
    await page.locator("#sb-new").click();
    await expect(page.locator("#sb-new")).toHaveText("New");
    await expect(page.locator("#sb-svg g.sb-node")).toHaveCount(0);
  });

  test("paste JSON loads a fenced Grok blob", async ({ page }) => {
    await openBuilder(page);
    const dlg = page.locator("#sb-paste");
    await expect(dlg).toBeHidden();
    await page.locator("#sb-paste-open").click();
    await expect(dlg).toBeVisible();
    const modal = await page.evaluate(() => document.getElementById("sb-paste").matches(":modal"));
    expect(modal).toBe(true);
    const blob = [
      "Here is the graph:",
      "```json",
      JSON.stringify({
        version: 1,
        title: "Pasted from Grok",
        nodes: [{ name: "Beta Fund", kind: "org", starting: true }],
        edges: [],
      }),
      "```",
    ].join("\n");
    await page.locator("#sb-paste-text").fill(blob);
    await page.locator("#sb-paste-form button[type='submit']").click();
    await expect(dlg).toBeHidden();
    await expect(page.locator("#sb-status")).toContainText("Pasted from Grok");
    await expect(page.locator("#sb-svg g.sb-node")).toHaveCount(1);
  });

  test("paste loads contract and dpa money kinds", async ({ page }) => {
    await openBuilder(page);
    await page.locator("#sb-paste-open").click();
    await page.locator("#sb-paste-text").fill(
      JSON.stringify({
        version: 1,
        title: "DoD to Acme",
        nodes: [
          { name: "DoD", kind: "gov", starting: true },
          { name: "Acme", kind: "org", starting: true },
        ],
        edges: [
          { from: "dod", to: "acme", kind: "contract", amount: 10 },
          { from: "dod", to: "acme", kind: "dpa", amount: 50 },
        ],
      }),
    );
    await page.locator("#sb-paste-form button[type='submit']").click();
    await expect(page.locator("#sb-status")).toContainText("DoD to Acme");
    await expect(page.locator("#sb-error")).toBeHidden();
    await expect(page.locator("#sb-svg path.sb-grant")).toHaveCount(2);
    await page.locator("#sb-view-table").click();
    await expect(page.locator('#sb-edges-table option[value="contract"][selected]')).toHaveCount(1);
    await expect(page.locator('#sb-edges-table option[value="dpa"][selected]')).toHaveCount(1);
  });

  test("disclaimer is a modal dialog", async ({ page }) => {
    await openBuilder(page);
    const dlg = page.locator("#sb-legal");
    await expect(dlg).toBeHidden();
    await page.locator("#sb-legal-open").click();
    await expect(dlg).toBeVisible();
    const modal = await page.evaluate(() => document.getElementById("sb-legal").matches(":modal"));
    expect(modal).toBe(true);
  });

  test("demo fixture draws grant and partner edges", async ({ page }) => {
    await openBuilder(page);
    await page.goto(HOST + "/sankeybuilder/?url=/sankeybuilder/fixtures/osf-alliance.json", {
      waitUntil: "load",
    });
    await expect(page.locator("#sb-status")).toContainText("OSF to Example Alliance");
    await expect(page.locator("#sb-svg g.sb-node")).toHaveCount(2);
    await expect(page.locator('#sb-click-mode [data-mode="add"]')).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await page.locator('#sb-svg g.sb-node[data-id="example-alliance"]').click();
    await expect(page.locator("#sb-svg g.sb-node")).toHaveCount(4);
    await page.locator("#sb-svg path.sb-hit").first().click();
    await expect(page.locator("#sb-edge-edit")).toBeVisible();
    await expect(page.locator("#sb-panel")).toContainText("Grant");
  });

  test("hovering a node or flow shows an info tip", async ({ page }) => {
    await openBuilder(page);
    await page.goto(HOST + "/sankeybuilder/?url=/sankeybuilder/fixtures/osf-alliance.json", {
      waitUntil: "load",
    });
    await expect(page.locator("#sb-svg g.sb-node")).toHaveCount(2);
    await page.locator('#sb-svg g.sb-node[data-id="example-alliance"]').hover();
    const tip = page.locator("#sb-graph-tip");
    await expect(tip).toBeVisible();
    await expect(tip).toContainText("Example Alliance");
    await expect(tip).toContainText("Gov $");
    const hit = page.locator("#sb-svg path.sb-hit").first();
    await hit.hover({ force: true });
    await expect(tip).toBeVisible();
    await expect(tip).toContainText("→");
  });

  test("table view lists hidden nodes and edits a grant", async ({ page }) => {
    await openBuilder(page);
    await page.goto(HOST + "/sankeybuilder/?url=/sankeybuilder/fixtures/osf-alliance.json", {
      waitUntil: "load",
    });
    await expect(page.locator("#sb-status")).toContainText("OSF to Example Alliance");
    await page.locator("#sb-view-table").click();
    await expect(page.locator("#sb-table")).toBeVisible();
    await expect(page.locator("#sb-view-diagram")).toBeVisible();
    await expect(
      page.locator('#sb-nodes-table input[name="name"][value="Jane Example"]'),
    ).toBeVisible();
    const amount = page.locator('#sb-edges-table input[name="amount"][value="10500000"]');
    await amount.fill("999");
    await amount.blur();
    await expect(page.locator("#sb-edge-edit")).toBeVisible();
    await expect(page.locator('#sb-edges-table input[name="amount"][value="999"]')).toBeVisible();
  });

  test("table Add row and Gov $ create an implied USG node", async ({ page }) => {
    await openBuilder(page);
    await page.locator("#sb-view-table").click();
    await expect(page.locator("#sb-table")).toBeVisible();
    await page.locator("#sb-table [data-add-node]").click();
    const name = page.locator('#sb-nodes-table input[name="name"]');
    await expect(name).toHaveValue("Untitled");
    const gov = page.locator('#sb-nodes-table input[name="govFunds"]');
    await gov.fill("5000");
    await gov.blur();
    await expect(
      page.locator('#sb-nodes-table input[name="name"][value="U.S. government"]'),
    ).toBeVisible();
    await page.locator("#sb-view-diagram").click();
    await expect(page.locator("#sb-svg g.sb-node")).toHaveCount(2);
    await expect(page.locator('#sb-svg g.sb-node[data-id="us-gov"]')).toHaveCount(1);
  });

  test("editor toggle hides the side panel", async ({ page }) => {
    await openBuilder(page);
    await expect(page.locator("#sb-panel")).toBeVisible();
    await expect(page.locator("#sb-view-editor")).toHaveText("Hide Editor");
    await page.locator("#sb-view-editor").click();
    await expect(page.locator("#sb")).toHaveAttribute("data-editor", "off");
    await expect(page.locator("#sb-view-editor")).toHaveText("Show Editor");
    await expect(page.locator("#sb-panel")).toBeHidden();
    await page.locator("#sb-view-editor").click();
    await expect(page.locator("#sb-panel")).toBeVisible();
  });

  test("inspect click opens a hidden editor for a node or grant", async ({ page }) => {
    await openBuilder(page);
    await page.goto(HOST + "/sankeybuilder/?url=/sankeybuilder/fixtures/osf-alliance.json", {
      waitUntil: "load",
    });
    await expect(page.locator("#sb-svg g.sb-node")).toHaveCount(2);
    await page.locator("#sb-view-editor").click();
    await expect(page.locator("#sb-panel")).toBeHidden();
    await page.locator('#sb-click-mode [data-mode="inspect"]').click();
    await page.locator('#sb-svg g.sb-node[data-id="example-alliance"]').click();
    await expect(page.locator("#sb")).toHaveAttribute("data-editor", "on");
    await expect(page.locator("#sb-panel")).toBeVisible();
    await expect(page.locator("#sb-node-form")).toBeVisible();
    await page.locator("#sb-view-editor").click();
    await expect(page.locator("#sb-panel")).toBeHidden();
    await page.locator("#sb-svg path.sb-hit").first().click({ force: true });
    await expect(page.locator("#sb-panel")).toBeVisible();
    await expect(page.locator("#sb-edge-edit")).toBeVisible();
  });

  test("controls toggle hides the canvas overlay", async ({ page }) => {
    await openBuilder(page);
    await expect(page.locator("#sb-controls")).toBeVisible();
    await expect(page.locator("#sb-zoom-in")).toBeVisible();
    await expect(page.locator("#sb-view-controls")).toHaveText("Hide Controls");
    await page.locator("#sb-view-controls").click();
    await expect(page.locator("#sb")).toHaveAttribute("data-controls", "off");
    await expect(page.locator("#sb-view-controls")).toHaveText("Show Controls");
    await expect(page.locator("#sb-controls")).toBeHidden();
    await page.locator("#sb-view-controls").click();
    await expect(page.locator("#sb-controls")).toBeVisible();
    await expect(page.locator("#sb-zoom-in")).toBeVisible();
  });

  test("help and share pages explain gist saving", async ({ page }) => {
    await page.goto(HOST + "/sankeybuilder/help/", { waitUntil: "load" });
    await expect(page.locator("h1")).toContainText(/How Show Don.t Tell works/);
    await expect(page.getByRole("link", { name: "Save and share" }).first()).toBeVisible();

    await page.goto(HOST + "/sankeybuilder/share/", { waitUntil: "load" });
    await expect(page.locator("h1")).toContainText("Save and share");
    await expect(page.locator("body")).toContainText("gist.github.com");
    await expect(page.locator("body")).toContainText("gist.githubusercontent.com");
    await expect(page.locator("body")).toContainText("Save JSON");
    await expect(page.locator("body")).toContainText("Save diagram");
  });

  test("extract prompt page loads", async ({ page, request }) => {
    const raw = await request.get(HOST + "/sankeybuilder/extract-prompt.txt");
    expect(raw.status()).toBe(200);
    const body = await raw.text();
    expect(body).toMatch(/Never invent an EIN/);
    expect(body).toMatch(/Do not ask the user to run follow-up prompts/);
    expect(body).toMatch(/Recursive research/);
    await page.goto(HOST + "/sankeybuilder/extract/", { waitUntil: "load" });
    await expect(page.locator("#extract-prompt")).toContainText(
      "https://gist.github.com/twinforces/706b11ec77740c11a1f258fc9d5030db",
    );
    await expect(page.locator("#extract-prompt")).toContainText("Read this gist");
    await expect(page.locator("#extract-prompt")).toContainText(
      "Then read the following post",
    );
    await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.locator("#copy-extract").click();
    await expect.poll(async () => page.evaluate(() => navigator.clipboard.readText())).toContain(
      "706b11ec77740c11a1f258fc9d5030db",
    );
  });

  test("share URL copies the fragment and says so", async ({ page }) => {
    await openBuilder(page);
    await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.locator('#sb-node-form input[name="name"]').fill("Solo");
    await page.locator('#sb-node-form button[type="submit"]').click();
    await page.locator("#sb-share").click();
    await expect(page.locator("#sb-share")).toHaveText("Copied to clipboard");
    await expect.poll(() => page.evaluate(() => location.hash.startsWith("#d="))).toBe(true);
  });

  test("extract from post opens a grok prompt link", async ({ page }) => {
    await openBuilder(page);
    await page.locator("#sb-post-url").fill(
      "https://x.com/labtechleigh/status/2118414465632739481",
    );
    await page.evaluate(() => {
      window.open = (url) => {
        window.__grokHref = url;
        return null;
      };
    });
    await page.locator("#sb-extract-post").click();
    const href = await page.evaluate(() => window.__grokHref);
    expect(href).toMatch(/^https:\/\/grok\.com\/\?/);
    expect(decodeURIComponent(href)).toContain(
      "https://gist.github.com/twinforces/706b11ec77740c11a1f258fc9d5030db",
    );
    expect(decodeURIComponent(href)).toContain(
      "https://x.com/labtechleigh/status/2118414465632739481",
    );
  });
});
