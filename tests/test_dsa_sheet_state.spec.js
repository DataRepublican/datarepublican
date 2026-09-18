const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* Closing the detail sheet must not disturb the graph.
 *
 * The sheet is a view of the selection, not the selection itself. Its close
 * handler used to run `cy.elements().removeClass('faded nbr sel')` — the
 * focus-OFF branch of the background-tap handler — unconditionally, including
 * in focus mode, which is the default. So on a phone you tapped a node to read
 * it, and dismissing what you were reading snapped the whole network back to
 * full strength and lost the walk.
 *
 * The graph's own deselect is a background tap, and it is conditional: focus
 * mode re-applies the ring, only focus-off clears.
 */

test.describe('dsa-explorer: dismissing the sheet leaves the graph alone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  const load = async (page) => {
    await page.goto(HOST + '/dsa-explorer/', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => typeof cy !== 'undefined' && cy.nodes && cy.nodes().length > 0,
      { timeout: 90000 }
    );
    await page.waitForTimeout(600);
  };

  // A node the app itself would open, walked through its own tap handler.
  const tapANode = (page) => page.evaluate(() => {
    const n = cy.nodes().filter(n => n.data('kind') === 'person').first();
    n.emit('tap');
    return n.id();
  });

  const state = (page) => page.evaluate(() => ({
    faded: cy.elements('.faded').length,
    sel: cy.elements('.sel').length,
    zoom: Math.round(cy.zoom() * 1000),
    pan: { x: Math.round(cy.pan().x), y: Math.round(cy.pan().y) },
  }));

  test('the fade survives the close button', async ({ page }) => {
    await load(page);
    // focusMode is module-scoped; aria-pressed is its public surface.
    await expect(page.locator('#focusToggle'), 'focus mode is the default')
      .toHaveAttribute('aria-pressed', 'true');

    await tapANode(page);
    await expect(page.locator('.dr-sheet')).toHaveClass(/is-open/, { timeout: 5000 });
    await page.waitForTimeout(800);            // let the 420ms focus glide settle

    const open = await state(page);
    expect(open.faded, 'tapping a node should fade the rest of the network').toBeGreaterThan(0);

    await page.locator('.dr-sheet__close').click();
    await expect(page.locator('.dr-sheet')).not.toHaveClass(/is-open/);
    await page.waitForTimeout(600);

    const closed = await state(page);
    expect(closed.faded, 'the network snapped back to full strength on close').toBe(open.faded);
    expect(closed.sel, 'the selected node lost its selection on close').toBe(open.sel);
    expect(closed.zoom, 'the camera moved on close').toBe(open.zoom);
    expect(closed.pan, 'the camera panned on close').toEqual(open.pan);
  });

  test('the fade survives a swipe down', async ({ page }) => {
    await load(page);
    await tapANode(page);
    await expect(page.locator('.dr-sheet')).toHaveClass(/is-open/, { timeout: 5000 });
    await page.waitForTimeout(800);
    const open = await state(page);

    /* Drag the grip until it actually closes, not just once.
       A drag past 120px steps DOWN one detent and only closes from the lowest,
       so from `half` a single drag lands on `peek` and never fires the close
       path at all — the first version of this test did exactly that and passed
       against the bug it was meant to catch. */
    const dragDown = async () => {
      const g = await page.locator('.dr-sheet__grip').boundingBox();
      if (!g) return;
      await page.mouse.move(g.x + g.width / 2, g.y + g.height / 2);
      await page.mouse.down();
      await page.mouse.move(g.x + g.width / 2, g.y + 260, { steps: 12 });
      await page.mouse.up();
      await page.waitForTimeout(400);
    };
    await dragDown();                                     // half -> peek
    await dragDown();                                     // peek -> closed
    await expect(page.locator('.dr-sheet')).not.toHaveClass(/is-open/);
    await page.waitForTimeout(400);

    const after = await state(page);
    expect(after.faded, 'the network reset after a swipe-down dismiss').toBe(open.faded);
    expect(after.zoom).toBe(open.zoom);
  });

  test('a background tap still deselects, because that IS the deselect gesture', async ({ page }) => {
    await load(page);
    await tapANode(page);
    await page.waitForTimeout(800);

    // Focus mode re-applies the ring rather than clearing to full strength —
    // the behaviour the close handler was wrongly borrowing.
    await page.evaluate(() => cy.emit('tap', [{ target: cy }]));
    await page.waitForTimeout(700);
    expect(await page.evaluate(() => cy.elements('.faded').length),
      'in focus mode a background tap returns to the ring, it does not clear').toBeGreaterThan(0);
  });
});
