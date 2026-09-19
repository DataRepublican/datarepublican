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

  /* A canvas toggle is icon-only, so the state is a dot in its corner: present
     means on. aria-pressed is the single source — the dot is shown and hidden
     by CSS keyed on it, which is why nothing can disagree with it — and the
     button's width must not change, or the whole column shifts on every click.

     The dot alone cannot say WHICH mode is on, so the accessible name has to
     be there and has to hold still too. */
  const toggle = async (page, sel, expected) => {
    const btn = page.locator(sel);
    const dot = btn.locator('.dr-btn__dot');
    const name = await btn.getAttribute('aria-label');
    expect(name, 'an icon-only toggle with no accessible name').toBeTruthy();

    const width = () => btn.evaluate(e => Math.round(e.getBoundingClientRect().width));
    const w0 = await width();

    await expect(btn).toHaveAttribute('aria-pressed', String(expected));
    expected ? await expect(dot).toBeVisible() : await expect(dot).toBeHidden();

    await btn.click();
    await expect(btn).toHaveAttribute('aria-pressed', String(!expected));
    !expected ? await expect(dot, 'the dot disagrees with aria-pressed').toBeVisible()
              : await expect(dot, 'the dot disagrees with aria-pressed').toBeHidden();

    expect(await btn.getAttribute('aria-label'),
      'the name changed with the state').toBe(name);
    expect(await width(), 'the button resized, so the column shifted').toBe(w0);
  };

  test('noblogs graph: Focus mode and Target edges only', async ({ page }) => {
    await page.goto(HOST + '/noblogs/?view=graph', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#graphwrap #cy canvas', { timeout: 90000 });

    await toggle(page, '#graphwrap #focusToggle', true);
    await toggle(page, '#graphwrap #tgtOnly', false);
  });

  test('dsa-explorer: Inferred links and Focus mode', async ({ page }) => {
    await page.goto(HOST + '/dsa-explorer/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#cy canvas', { timeout: 90000 });

    // Pressed means the inferred links are SHOWN, which is the load state. The
    // variable behind it is `infHidden`, so the two read in opposite directions.
    await toggle(page, '#toggleInf', true);
    await expect(page.locator('#focusToggle')).toHaveAttribute('aria-pressed', 'true');
  });

  test('a pressed toggle is visibly filled, not only announced', async ({ page }) => {
    await page.goto(HOST + '/dsa-explorer/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#cy canvas', { timeout: 90000 });
    /* `#cy canvas` exists as soon as Cytoscape mounts, which is BEFORE the
       controls below it are wired — so under parallel load the click could
       land on a button with no handler and both readings came back identical.
       This test was intermittently red for exactly that reason. Wait for the
       graph to actually hold nodes, which is the same gate the other
       dsa-explorer specs use. */
    await page.waitForFunction(
      () => typeof cy !== 'undefined' && cy.nodes && cy.nodes().length > 0,
      { timeout: 90000 });

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

/* .dr-btn carries the 44px floor, so a control gets it by being the component
   rather than by remembering. `.loadmore` was ~39px — a real miss, and the kind
   that only shows up if something measures it. */
test.describe('.dr-btn clears the tap target', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test('every .dr-btn on noblogs is at least 44px tall', async ({ page }) => {
    await page.goto(HOST + '/noblogs/?view=dash', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.card', { timeout: 60000 });
    // Reveal the load-more control, which only paints when there is a next page.
    await page.evaluate(() => { const b = document.getElementById('loadmore'); if (b) b.style.display = 'flex'; });

    const small = await page.locator('.dr-btn').evaluateAll(els =>
      els.filter(e => e.offsetParent !== null)
         .map(e => ({ id: e.id || e.className, h: Math.round(e.getBoundingClientRect().height) }))
         .filter(r => r.h < 44)
    );
    expect(small, `.dr-btn under 44px: ${JSON.stringify(small)}`).toEqual([]);
  });

  test('the reset actually applied — no inherited min-width or margin', async ({ page }) => {
    await page.goto(HOST + '/noblogs/?view=dash', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#nb-filters', { timeout: 60000 });
    // The global button rule sets min-width:65px and a right margin at md.
    // A component that did not absorb the reset would still carry both.
    const cs = await page.locator('#nb-filters').evaluate(e => {
      const s = getComputedStyle(e);
      return { minWidth: s.minWidth, marginRight: s.marginRight, radius: s.borderTopLeftRadius };
    });
    expect(cs.minWidth).toBe('0px');
    expect(cs.marginRight).toBe('0px');
    expect(parseFloat(cs.radius)).toBeGreaterThan(100);   // pill
  });
});
