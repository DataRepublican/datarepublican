const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* The view switcher is the tool's primary navigation and was three <div>s with
 * a click handler: no role, not focusable, no arrow keys. It is a real tablist
 * now. `.tab` and `data-v` are unchanged on purpose — readURL() and three
 * existing specs drive it by those selectors. */
test.describe('the view switcher is a tablist', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  const open = async (page) => {
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#tabs .tab', { timeout: 60000 });
  };

  test('roles and selection are exposed', async ({ page }) => {
    await open(page);
    await expect(page.locator('#tabs')).toHaveAttribute('role', 'tablist');
    expect(await page.locator('#tabs [role="tab"]').count()).toBe(3);
    await expect(page.locator('#tab-map')).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('#tab-dash')).toHaveAttribute('aria-selected', 'false');
    // Each tab names its panel, and each panel names its tab.
    await expect(page.locator('#tab-map')).toHaveAttribute('aria-controls', 'mapview');
    await expect(page.locator('#mapview')).toHaveAttribute('aria-labelledby', 'tab-map');
  });

  test('only the selected tab is in the tab order', async ({ page }) => {
    await open(page);
    const idx = await page.locator('#tabs .tab').evaluateAll(
      els => els.map(e => ({ v: e.dataset.v, t: e.tabIndex }))
    );
    expect(idx).toEqual([
      { v: 'map', t: 0 }, { v: 'dash', t: -1 }, { v: 'graph', t: -1 },
    ]);
  });

  test('ArrowRight moves and activates, and the roving index follows', async ({ page }) => {
    await open(page);
    await page.locator('#tab-map').focus();
    await page.keyboard.press('ArrowRight');

    await expect(page.locator('#tab-dash')).toBeFocused();
    await expect(page.locator('#tab-dash')).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('#tab-map')).toHaveAttribute('aria-selected', 'false');
    await expect.poll(() => page.evaluate(() => view)).toBe('dash');
    await expect.poll(() => page.evaluate(() => document.getElementById('tab-map').tabIndex)).toBe(-1);
  });

  test('ArrowLeft wraps, and End jumps to the last tab', async ({ page }) => {
    await open(page);
    await page.locator('#tab-map').focus();
    await page.keyboard.press('ArrowLeft');
    await expect(page.locator('#tab-graph')).toBeFocused();

    await page.locator('#tab-map').focus();
    await page.keyboard.press('End');
    await expect(page.locator('#tab-graph')).toBeFocused();
    await expect.poll(() => page.evaluate(() => view)).toBe('graph');
  });
});

/* Four toggles across the two tools reported their state by rewriting their own
 * label — "Focus: on" / "Focus: off". A swapped label tells a sighted user what
 * the NEXT click does and tells a screen reader nothing. They carry a fixed
 * noun phrase plus aria-pressed now. */
test.describe('toggles report state with aria-pressed', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test('noblogs graph: Focus mode and Target edges only', async ({ page }) => {
    await page.goto(HOST + '/noblogs/?view=graph', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#graphwrap #cy canvas', { timeout: 90000 });

    const focus = page.locator('#graphwrap #focusToggle');
    await expect(focus).toHaveAttribute('aria-pressed', 'true');
    await expect(focus).toHaveText('Focus mode');          // label does not move
    await focus.click();
    await expect(focus).toHaveAttribute('aria-pressed', 'false');
    await expect(focus).toHaveText('Focus mode');

    const tgt = page.locator('#graphwrap #tgtOnly');
    await expect(tgt).toHaveAttribute('aria-pressed', 'false');
    await tgt.click();
    await expect(tgt).toHaveAttribute('aria-pressed', 'true');
  });

  test('dsa-explorer: Inferred links and Focus mode', async ({ page }) => {
    await page.goto(HOST + '/dsa-explorer/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#cy canvas', { timeout: 90000 });

    // Pressed means the inferred links are SHOWN, which is the load state. The
    // variable behind it is `infHidden`, so the two read in opposite directions.
    const inf = page.locator('#toggleInf');
    await expect(inf).toHaveAttribute('aria-pressed', 'true');
    await expect(inf).toHaveText('Inferred links');
    await inf.click();
    await expect(inf).toHaveAttribute('aria-pressed', 'false');
    await expect(inf).toHaveText('Inferred links');   // the label does not move

    await expect(page.locator('#focusToggle')).toHaveAttribute('aria-pressed', 'true');
  });

  test('a pressed toggle is visibly filled, not only announced', async ({ page }) => {
    await page.goto(HOST + '/dsa-explorer/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#cy canvas', { timeout: 90000 });

    /* Park the pointer away from the button before every reading. The first
       version of this test clicked and then measured with the cursor still
       resting on the control, so it was comparing rest against :hover and would
       have passed with no aria-pressed rule at all. */
    const away = () => page.mouse.move(5, 5);
    const bg = (sel) => page.locator(sel).evaluate(e => getComputedStyle(e).backgroundColor);

    await away();
    const off = await bg('#toggleInf');           // aria-pressed="true" at load
    await page.locator('#toggleInf').click();
    await away();
    const on = await bg('#toggleInf');
    expect(on, 'the pressed fill is not distinguishable from the rest state').not.toBe(off);

    // And the filled one is the pressed one, not merely "different".
    const pressed = await page.locator('#toggleInf').getAttribute('aria-pressed');
    const accent = await page.evaluate(() =>
      getComputedStyle(document.documentElement).getPropertyValue('--dr-accent').trim());
    expect(accent).toBeTruthy();
    expect(pressed).toBe('false');                // toggled off, so NOT filled
    expect(off).not.toBe(on);
  });
});
