const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* DRTip replaced `title` on every toolbar control.
 *
 * The native tooltip waits about a second, which on an icon-only control is the
 * whole interaction: you hover a glyph you do not recognize, get nothing, and
 * move on. These specs hold the three properties that made it worth replacing —
 * it is instant, it is the ONLY tooltip (both would stack and read twice), and
 * it survives the isolated canvases the tools use to contain Leaflet and
 * Cytoscape.
 */

const TOOLS = [
  { name: 'noblogs graph', path: '/noblogs/?view=graph', ready: '#graphwrap #cy canvas',
    scope: '#graphwrap #controls', ambiguous: '#relayout' },
  { name: 'dsa-explorer', path: '/dsa-explorer/', ready: '#cy canvas',
    scope: '#controls', ambiguous: '#relayout' },
];

for (const t of TOOLS) {
  test.describe(`${t.name} tooltips`, () => {
    test.use({ viewport: { width: 1280, height: 900 } });

    const load = async (page) => {
      await page.goto(HOST + t.path, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector(t.ready, { timeout: 90000 });
      await page.waitForSelector(`${t.scope} .dr-btn`, { timeout: 30000 });
    };

    test('every control has one, and none keeps a native title', async ({ page }) => {
      await load(page);
      const r = await page.evaluate((scope) => {
        const btns = [...document.querySelectorAll(`${scope} button`)];
        return {
          total: btns.length,
          untipped: btns.filter(b => !b.getAttribute('data-tip')).map(b => b.id),
          titled: btns.filter(b => b.title).map(b => b.id),
          unnamed: btns.filter(b => !b.textContent.trim() && !b.getAttribute('aria-label')).map(b => b.id),
        };
      }, t.scope);

      expect(r.total).toBeGreaterThan(4);
      expect(r.untipped, `no tooltip: ${r.untipped}`).toEqual([]);
      // Both would stack the native tip under ours and read the text twice.
      expect(r.titled, `still carrying title=: ${r.titled}`).toEqual([]);
      expect(r.unnamed, `icon-only with no accessible name: ${r.unnamed}`).toEqual([]);
    });

    test('appears instantly on hover and describes the control', async ({ page }) => {
      await load(page);
      await page.locator(`${t.scope} ${t.ambiguous}`).hover();

      // No timeout: instant is the entire reason this exists. Polling here
      // would pass with a one-second delay reinstated.
      const tip = await page.evaluate(() => {
        const el = document.getElementById('dr-tip');
        return el && !el.hidden ? { text: el.textContent, on: el.classList.contains('is-on') } : null;
      });
      expect(tip, 'the tooltip did not appear on hover').not.toBeNull();
      expect(tip.on).toBe(true);
      expect(tip.text.length, 'an ambiguous control needs a sentence').toBeGreaterThan(30);

      // Described, not named: the control keeps its own accessible name.
      await expect(page.locator(`${t.scope} ${t.ambiguous}`))
        .toHaveAttribute('aria-describedby', 'dr-tip');
    });

    test('renders above the isolated canvas, not trapped inside it', async ({ page }) => {
      await load(page);
      await page.locator(`${t.scope} ${t.ambiguous}`).hover();

      const r = await page.evaluate(() => {
        const el = document.getElementById('dr-tip');
        const box = el.getBoundingClientRect();
        return {
          parentIsBody: el.parentElement === document.body,
          z: Number(getComputedStyle(el).zIndex),
          w: Math.round(box.width), h: Math.round(box.height),
          left: Math.round(box.left), right: Math.round(box.right),
        };
      });

      /* Appended to <body>, because #stage sets `isolation: isolate` to contain
         the vendor's z-indexes — a tip rendered inside is trapped in that
         stacking context and clipped by the stage's overflow. */
      expect(r.parentIsBody, 'a tip inside the canvas is clipped by it').toBe(true);
      expect(r.z, 'nothing this repo authors goes above 100').toBeLessThanOrEqual(100);
      expect(r.w).toBeGreaterThan(0);
      expect(r.h).toBeGreaterThan(0);
      // Clamped into the viewport rather than hanging off the edge.
      expect(r.left).toBeGreaterThanOrEqual(0);
      expect(r.right).toBeLessThanOrEqual(1280);
    });

    /* A dot says a mode is on but not which, and not what it is set to when you
       are hovering the one you are unsure about. DRTip reads `aria-pressed`, so
       the assertion is that the chip tracks the CONTROL rather than a string
       someone remembered to update. */
    test('a toggle says ON or OFF, and the chip flips with the control', async ({ page }) => {
      await load(page);
      const toggle = page.locator(`${t.scope} .dr-btn[aria-pressed]`).first();

      const chip = () => page.evaluate(() => {
        const s = document.querySelector('#dr-tip .dr-tip__state');
        return s ? { text: s.textContent.trim(), state: s.getAttribute('data-state') } : null;
      });

      await toggle.hover();
      const before = await chip();
      expect(before, 'a two-state control showed no state in its tooltip').not.toBeNull();
      expect(before.text).toBe(await toggle.getAttribute('aria-pressed') === 'true' ? 'ON' : 'OFF');

      // Clicking under the pointer must re-render: a tip left reading ON right
      // after the mode was switched off is worse than no tip at all.
      await toggle.click();
      const after = await chip();
      expect(after, 'the tooltip vanished instead of updating').not.toBeNull();
      expect(after.text, 'the tooltip still reads the old state').not.toBe(before.text);
      expect(after.text).toBe(await toggle.getAttribute('aria-pressed') === 'true' ? 'ON' : 'OFF');
    });

    /* A plain action has no state, so it must not grow a chip. */
    test('a control that only does something shows no ON/OFF', async ({ page }) => {
      await load(page);
      await page.locator(`${t.scope} ${t.ambiguous}`).hover();
      expect(await page.locator('#dr-tip .dr-tip__state').count()).toBe(0);
    });

    test('goes away on leave, and on Escape', async ({ page }) => {
      await load(page);
      const up = () => page.evaluate(() => {
        const el = document.getElementById('dr-tip');
        return !!(el && !el.hidden);
      });

      await page.locator(`${t.scope} ${t.ambiguous}`).hover();
      expect(await up()).toBe(true);
      await page.mouse.move(5, 5);
      expect(await up(), 'the tip outlived the pointer').toBe(false);

      // Keyboard users get it on focus, and Escape dismisses it.
      await page.locator(`${t.scope} ${t.ambiguous}`).focus();
      expect(await up(), 'no tooltip on keyboard focus').toBe(true);
      await page.keyboard.press('Escape');
      expect(await up()).toBe(false);
    });
  });
}

/* The case the whole `aria-disabled` choice exists for.
 *
 * dsa-explorer's Back starts unavailable — there is nowhere to go back to on
 * arrival — and it is icon-only, so a grayed chevron with no tooltip is a
 * control nobody can identify. A real `disabled` attribute makes that
 * permanent: the browser dispatches no pointer events over a disabled element,
 * so hover never reaches DRTip and the explanation can never open.
 */
test.describe('dsa-explorer Back while it is unavailable', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test('is visibly off, still explains itself, and does nothing when clicked', async ({ page }) => {
    await page.goto(HOST + '/dsa-explorer/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#cy canvas', { timeout: 90000 });
    const back = page.locator('#controls #back');

    await expect(back).toHaveAttribute('aria-disabled', 'true');
    // `disabled` would suppress the hover the tooltip needs.
    expect(await back.evaluate(b => b.disabled), 'a disabled button cannot be hovered').toBe(false);

    await back.hover();
    const tip = await page.evaluate(() => {
      const el = document.getElementById('dr-tip');
      return el && !el.hidden ? el.textContent : null;
    });
    expect(tip, 'an unavailable icon-only control with no explanation').not.toBeNull();
    // Not just the name: it has to say what would make it available.
    expect(tip.length).toBeGreaterThan(40);

    /* aria-disabled is not inert — the browser will happily run the handler —
       so the guard has to be in the handler. dispatchEvent rather than click()
       on purpose: Playwright's own actionability check refuses to click an
       aria-disabled element, which would test Playwright rather than the app. */
    await back.dispatchEvent('click');
    await expect(back).toHaveAttribute('aria-disabled', 'true');
  });
});
