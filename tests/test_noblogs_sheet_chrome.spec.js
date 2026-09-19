const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

/* The bottom sheet's own chrome, and the things a consumer has to agree with it
 * about. All three failures here were visible on /noblogs/?view=dash with a
 * blog selected, and all three came from the sheet and the panel it wraps
 * making different assumptions.
 */

test.describe('the noblogs detail sheet', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  const openSheet = async (page) => {
    await page.goto(
      HOST + '/noblogs/?view=dash&host=antifascistchicago.noblogs.org',
      { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.dr-sheet.is-open', { timeout: 60000 });
    await page.waitForTimeout(400); // the rise
  };

  test('has ONE close button, not two', async ({ page }) => {
    await openSheet(page);
    // DRSheet puts a close in its wrapper and the tool has its own .pclose.
    // Stacked on a phone, the panel grew two X's in two header bars.
    const visible = await page.evaluate(() => {
      const inSheet = [...document.querySelectorAll('.dr-sheet button')];
      return inSheet.filter(b => {
        const r = b.getBoundingClientRect();
        return r.width > 0 && r.height > 0 &&
          (b.className || '').match(/close|pclose/);
      }).map(b => b.className);
    });
    expect(visible, `close buttons visible: ${JSON.stringify(visible)}`).toHaveLength(1);
  });

  test('is one continuous surface — no white band above or below the content', async ({ page }) => {
    await openSheet(page);
    // The sheet, its grip and the panel it wraps are three elements painting
    // what has to look like one surface, and each had its own idea of the
    // colour — so the grip row and the padding below the body read as a header
    // and a footer the sheet does not have. Whatever the ground is, all three
    // have to name it.
    const c = await page.evaluate(() => {
      const sheet = document.querySelector('.dr-sheet');
      const grip = document.querySelector('.dr-sheet__grip');
      const panel = document.getElementById('panel');
      const bg = el => getComputedStyle(el).backgroundColor;
      return { sheet: bg(sheet), grip: bg(grip), panel: bg(panel) };
    });
    expect(c.sheet).toBe(c.panel);
    expect(c.grip).toBe(c.panel);
  });

  test('reserves room for the close button at the top', async ({ page }) => {
    await openSheet(page);
    // The grip is the sheet's header row and has to be at least as tall as the
    // 44px close pinned into it, or the close overhangs whatever the panel
    // renders first.
    const m = await page.evaluate(() => {
      const grip = document.querySelector('.dr-sheet__grip').getBoundingClientRect();
      const close = document.querySelector('.dr-sheet__close').getBoundingClientRect();
      const body = document.getElementById('panel').getBoundingClientRect();
      return { gripH: Math.round(grip.height), closeBottom: close.bottom, bodyTop: body.top };
    });
    expect(m.gripH).toBeGreaterThanOrEqual(44);
    expect(m.closeBottom, 'the close button overhangs the panel content')
      .toBeLessThanOrEqual(m.bodyTop + 1);
  });
});

test.describe('the desktop detail drawer', () => {
  test.use({ viewport: { width: 1400, height: 900 } });

  /* The overlay is the List view's form. That view already spends a column on
     the facet rail and a third would cost half the card grid, so the detail
     still arrives over the top of it. The canvas views get the sidebar below. */
  test('fills the viewport at any scroll position', async ({ page }) => {
    /* #panel and #scrim were inset by --nb-header-h, which is the tool
       header's HEIGHT and not its distance from the top of the window. Those
       agree only when the page is scrolled far enough for the sticky header to
       be pinned at top:0 — at every other scroll position the drawer started
       partway down the masthead and the scrim left a live, clickable strip of
       page above itself.

       A length standing in for a position is the whole bug, so the assertion
       is simply that neither depends on scroll. */
    await page.goto(
      HOST + '/noblogs/?view=dash&host=vernetzungpartizipation.noblogs.org',
      { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#panel.on', { timeout: 90000 });
    await page.waitForTimeout(400);

    const box = () => page.evaluate(() => {
      const p = document.getElementById('panel').getBoundingClientRect();
      const s = document.getElementById('scrim').getBoundingClientRect();
      return {
        panelTop: Math.round(p.top), panelBottom: Math.round(p.bottom),
        scrimTop: Math.round(s.top), scrimHeight: Math.round(s.height),
        vh: window.innerHeight,
      };
    });

    const atTop = await box();
    expect(atTop.panelTop, 'the drawer does not reach the top of the window').toBe(0);
    expect(atTop.panelBottom).toBe(atTop.vh);
    expect(atTop.scrimTop, 'live page above the scrim').toBe(0);
    expect(atTop.scrimHeight).toBe(atTop.vh);

    await page.evaluate(() => window.scrollTo(0, 300));
    await page.waitForTimeout(200);
    const scrolled = await box();
    expect(scrolled, 'the drawer moved with the page').toEqual(atTop);
  });
});

/* The canvas views carry a persistent sidebar instead, scoped to the stage the
 * way dsa-explorer's is: categories by default, the detail in the same column
 * when a node is picked. The two tools were solving one problem two ways —
 * this is the shared answer, and openModal/closeModal are unchanged by it.
 * They toggle `.on` and `SEL`; the placement is CSS keyed on body[data-view]. */
test.describe('the canvas-view sidebar', () => {
  test.use({ viewport: { width: 1400, height: 900 } });

  const geom = (page) => page.evaluate(() => {
    const p = document.getElementById('panel');
    const r = p.getBoundingClientRect();
    const map = document.getElementById('mapwrap').getBoundingClientRect();
    return {
      position: getComputedStyle(p).position,
      bg: getComputedStyle(p).backgroundColor,
      scrim: getComputedStyle(document.getElementById('scrim')).display,
      clearsCanvas: r.left >= map.right - 1,
      cats: !!document.querySelector('#nb-side-cats .fitem[data-f="cat"]')?.offsetParent,
      detail: !!document.getElementById('pinner').offsetParent,
      close: !!document.querySelector('#panel .pclose')?.offsetParent,
      right: Math.abs(r.right - document.querySelector('#panel .pclose').getBoundingClientRect().right),
    };
  });

  test('it sits beside the canvas rather than over it, on white', async ({ page }) => {
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.leaflet-marker-icon, .marker-cluster', { timeout: 90000 });

    const g = await geom(page);
    expect(g.position, 'the sidebar is still an overlay').toBe('static');
    expect(g.scrim, 'a sidebar does not dim the page behind it').toBe('none');
    expect(g.clearsCanvas, 'the sidebar is covering the map').toBe(true);
    // A panel surface, not the page ground it is sitting on.
    expect(g.bg).toBe('rgb(255, 255, 255)');

    // Categories, and no way back from a place you have not left.
    expect(g.cats).toBe(true);
    expect(g.detail).toBe(false);
    expect(g.close).toBe(false);
  });

  test('picking a blog swaps categories for the detail, and back', async ({ page }) => {
    await page.goto(
      HOST + '/noblogs/?view=map&host=vernetzungpartizipation.noblogs.org',
      { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#pinner h2', { timeout: 90000 });

    const g = await geom(page);
    expect(g.detail).toBe(true);
    expect(g.cats, 'both halves are showing at once').toBe(false);
    expect(g.close).toBe(true);
    // The close is at the trailing edge. As a flex item with a stale
    // `float:right` it stretched full width and centred its glyph instead.
    expect(g.right, 'the close button is not on the right').toBeLessThan(20);

    await page.click('#panel .pclose');
    await expect.poll(async () => (await geom(page)).cats).toBe(true);
    expect((await geom(page)).detail).toBe(false);
  });

  /* The radius is cosmetic; the `overflow:hidden` under it is not. Leaflet's
     tiles and Cytoscape's canvas are opaque children that square the corners
     off without it, so the rule reads as applied and does nothing. Both tools,
     because they round the band two different ways — one wrapper on noblogs,
     matching half-radii on dsa-explorer, whose header shares the grid. */
  for (const [name, url, sel] of [
    ['noblogs', '/noblogs/?view=map', '#nb-stage'],
    ['dsa-explorer', '/dsa-explorer/', '#stage'],
  ]) {
    test(`${name}: the canvas band is rounded and actually clips`, async ({ page }) => {
      await page.goto(HOST + url, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector(sel, { timeout: 90000 });
      const cs = await page.locator(sel).evaluate(e => {
        const s = getComputedStyle(e);
        return { tl: parseFloat(s.borderTopLeftRadius), oflow: s.overflow };
      });
      expect(cs.tl, 'the band is not rounded').toBeGreaterThan(6);
      expect(cs.oflow, 'the radius is decorative — the canvas paints over it')
        .toBe('hidden');
    });
  }
});

test.describe('the graph cross-filter', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test('an empty host set empties the graph, it does not fill it', async ({ page }) => {
    /* applyGraphFilter tested `hosts.length`, which collapses "the filter
       matched nothing" ([]) into "there is no filter" (null) — so a facet
       combination with no results showed the WHOLE network. map.js guards the
       same call with Array.isArray and was always correct.

       Driven through the API rather than the search box: on this view the text
       query finds rather than filters, so it can no longer produce an empty
       host set. The contract is still the contract. */
    await page.goto(HOST + '/noblogs/?view=graph', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => typeof graphApi !== 'undefined' && graphApi && graphApi.cy.nodes().length > 0,
      { timeout: 90000 });

    const shown = () => page.evaluate(
      () => cy.nodes('[kind="blog"]').filter(n => n.style('display') !== 'none').length);
    const set = async (hosts) => {
      await page.evaluate((h) => graphApi.setHosts(h), hosts);
      await page.waitForTimeout(300);
    };

    const all = await shown();
    expect(all).toBeGreaterThan(0);

    const two = await page.evaluate(
      () => cy.nodes('[kind="blog"]').slice(0, 2).map(n => n.id()));
    await set(two);
    expect(await shown(), 'a real host set should narrow the graph').toBe(2);

    await set([]);
    expect(await shown(), 'an empty host set rendered as the whole network').toBe(0);

    await set(null);
    expect(await shown(), 'null means no filter and should restore every node').toBe(all);
  });

  test('on Graph the header search finds instead of filtering', async ({ page }) => {
    /* One box, and it means what the view means.
       On Map and List the query NARROWS the corpus. On Graph it must not: the
       network holds 217 of 7,673 blogs, so "berlin" (349 corpus hits, 7 of them
       nodes) emptied the view, and naming an institution could never work at
       all — the 77 institutions are not rows in the blog index. So there the
       query highlights and frames instead, and only the facets filter. */
    await page.goto(HOST + '/noblogs/?view=graph', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => typeof graphApi !== 'undefined' && graphApi && graphApi.cy.nodes().length > 0,
      { timeout: 90000 });
    await page.waitForTimeout(600);

    const reach = await page.evaluate(() => ({
      institutions: cy.nodes('[kind="institution"]').length,
      inBlogData: cy.nodes('[kind="institution"]').filter(n => BYHOST[n.id()]).length,
    }));
    expect(reach.institutions).toBeGreaterThan(0);
    expect(reach.inBlogData, 'institutions are not in the blog index').toBe(0);

    const state = () => page.evaluate(() => ({
      visible: cy.nodes().filter(n => n.style('display') !== 'none').length,
      hits: cy.$('.nbr').length,
      offScreen: cy.$('.nbr').filter(n => n.style('display') === 'none').length,
      status: document.getElementById('subcount').textContent,
    }));
    const type = async (v) => {
      await page.evaluate((s) => {
        const f = document.getElementById('search');
        f.value = s;
        f.dispatchEvent(new Event('input'));
      }, v);
      await page.waitForTimeout(700); // both debounces
    };

    const before = await state();
    expect(before.visible).toBeGreaterThan(200);

    // The query that used to empty the graph.
    await type('berlin');
    const after = await state();
    expect(after.visible, 'the query narrowed the network instead of searching it')
      .toBe(before.visible);
    expect(after.hits, 'nothing was highlighted').toBeGreaterThan(0);
    expect(after.offScreen, 'highlighted something the facets had hidden').toBe(0);

    // An institution, which no filtering search could ever return.
    await type('adl');
    const inst = await state();
    expect(inst.visible).toBe(before.visible);
    const lit = await page.evaluate(
      () => cy.$('.nbr').filter(n => n.data('kind') === 'institution').length);
    expect(lit, 'institutions are unreachable from the header search').toBeGreaterThan(0);

    // The status line counts nodes here, never the 7,673-row corpus.
    expect(inst.status).not.toMatch(/7,673/);
    expect(inst.status).toMatch(/node/i);

    // A miss says so rather than emptying the view.
    await type('zzzzznomatch');
    const miss = await state();
    expect(miss.visible).toBe(before.visible);
    expect(miss.hits).toBe(0);
    expect(miss.status).toMatch(/No nodes match/i);
  });
});

test.describe('the filter popover reset', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  const openFilters = async (page) => {
    await page.goto(HOST + '/noblogs/?view=map', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#nb-filters', { timeout: 60000 });
    await page.click('#nb-filters');
    await page.waitForSelector('#facets .clearf', { timeout: 30000 });
  };

  test('is titled, and the reset sits opposite the title', async ({ page }) => {
    await openFilters(page);
    const clear = page.locator('#facets .clearf');

    // The panel says what it is, so the reset does not have to. "✕ clear all
    // filters" was a lone link above the first group with nothing to anchor
    // it, and it read as that group's first item.
    await expect(page.locator('#facets .fhead h2')).toHaveText('Filters');
    await expect(clear).toHaveText('Clear');

    // Named region rather than an unlabelled one.
    await expect(page.locator('#facets'))
      .toHaveAttribute('aria-labelledby', 'facets-title');

    // Trailing edge of the header row, opposite the title.
    const laid = await page.evaluate(() => {
      const el = document.querySelector('#facets .clearf');
      const h = document.querySelector('#facets .fhead h2');
      const head = document.querySelector('#facets .fhead');
      const er = el.getBoundingClientRect();
      const hr = h.getBoundingClientRect();
      const fr = head.getBoundingClientRect();
      return { afterTitle: er.left > hr.right, atEdge: Math.abs(fr.right - er.right) < 6 };
    });
    expect(laid.afterTitle, 'the reset is not opposite the title').toBe(true);
    expect(laid.atEdge, 'the reset is not at the trailing edge').toBe(true);

    await expect(clear).toBeDisabled();
    await page.locator('#facets .fitem[data-f="cat"] input').first().check();
    await expect(clear).toBeEnabled();
  });

  test('the count badge is not vertically squashed', async ({ page }) => {
    await openFilters(page);
    await page.locator('#facets .fitem[data-f="cat"] input').first().check();
    await page.waitForTimeout(200);

    const b = await page.locator('#nb-filtercount').evaluate(e => {
      const r = e.getBoundingClientRect();
      return { w: r.width, h: r.height };
    });
    // A flex item with only padding gets squashed to the line box. It has to
    // state its own box, and a single digit should be round-ish.
    expect(b.h).toBeGreaterThanOrEqual(18);
    expect(Math.abs(b.w - b.h), `badge is ${b.w}x${b.h}`).toBeLessThan(6);
  });
});
