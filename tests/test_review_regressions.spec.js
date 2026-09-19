const { test, expect } = require('@playwright/test');

const HOST = process.env.HOST || 'http://localhost:4000';

// Three blockers a code review caught that the existing suite did not. Each was
// a selector left pointing at something a refactor had renamed or restructured,
// so the page rendered and the data was right — only a control was dead. The
// specs below exercise the control, not its presence.

test.describe('graph chrome survives the extraction', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  const load = async (page) => {
    await page.goto(HOST + '/noblogs/graph/', { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => typeof cy !== 'undefined' && typeof cy.nodes === 'function' && cy.nodes().length > 0,
      { timeout: 90000 }
    );
    await page.waitForTimeout(2500);
  };

  test('the detail panel actually collapses', async ({ page }) => {
    await load(page);
    // graph.js puts `collapsed` on the root, but the CSS still said
    // `.nbgraph #app.collapsed` — #app having been deleted by the extraction.
    // Nothing matched, so the graph booted showing an empty 370px aside.
    //
    // Driven by SELECTING A NODE, not by a chevron. The #panelToggle button is
    // gone: the panel opens when there is something to put in it and closes
    // when there is not, so selection is the only path that still exists. The
    // property under test is unchanged — `.collapsed` has to really move the
    // grid column.
    const cols = () => page.evaluate(
      () => getComputedStyle(document.getElementById('graphroot')).gridTemplateColumns
    );
    const collapsed = await cols();
    expect(collapsed, 'boots collapsed, with nothing selected').not.toMatch(/370px/);

    // 'institution', not 'inst' — graph_data.js spells it out.
    await page.evaluate(() => cy.nodes('[kind = "institution"]').first().emit('tap'));
    await page.waitForTimeout(300);
    const expanded = await cols();
    expect(collapsed).not.toBe(expanded);
    expect(expanded).toMatch(/370px/);
  });

  test('the canvas carries no search field of its own', async ({ page }) => {
    await load(page);
    /* There were three versions of a canvas search here — a 270px field parked
       top-center, then one hidden behind a toolbar button, then one growing out
       of that button — before the answer turned out to be that the graph should
       not have its own field at all. The explorer's header field IS the graph's
       search on this view (NBGraph.find), so a second box is a second place to
       type the same thing. */
    const found = await page.evaluate(() => ({
      gsearch: !!document.getElementById('gsearch'),
      q: !!document.getElementById('q'),
      inputsOnCanvas: document.querySelectorAll('#stage input').length,
    }));
    expect(found.gsearch).toBe(false);
    expect(found.q).toBe(false);
    expect(found.inputsOnCanvas, 'a search field crept back onto the canvas').toBe(0);

    // `graphApi` is the EXPLORER's handle and does not exist on this page, so
    // the module's own export is what to check here.
    expect(await page.evaluate(() => typeof NBGraph.init)).toBe('function');
  });
});

test.describe('dsa-explorer legend is reachable on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test('the toggle is visible and opens the ideology filter', async ({ page }) => {
    await page.goto(HOST + '/dsa-explorer/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#cy canvas', { timeout: 90000 });
    await page.waitForTimeout(3500);

    // The mobile rule hid .legbar — which contains .legtoggle, the only control
    // that can expand the legend. The ideology filter, the tool's main faceting
    // control, was unreachable on a phone.
    const toggle = page.locator('#legToggle');
    await expect(toggle).toBeVisible();
    expect(await toggle.evaluate((e) => Math.round(e.getBoundingClientRect().height)))
      .toBeGreaterThanOrEqual(44);

    await expect(page.locator('#legend .legchips')).toBeHidden();
    await toggle.click();
    await expect(page.locator('#legend .legchips')).toBeVisible();
  });
});

test.describe('standalone map popup', () => {
  test.use({ viewport: { width: 1200, height: 800 } });

  test('offers a way to reach the blog', async ({ page }) => {
    await page.goto(HOST + '/noblogs/world_hyperlocal_map.html', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.leaflet-marker-icon, .marker-cluster', { timeout: 90000 });
    await page.waitForTimeout(2500);

    // Rewriting the popup dropped the hostname and the outbound link. On this
    // page the popup IS the detail view, so there was no way to reach the blog.
    const openOne = async () => {
      await page.evaluate(() => document.querySelector('.leaflet-marker-icon')?.click());
      await page.waitForTimeout(800);
      return page.locator('.leaflet-popup-content').first().innerHTML().catch(() => '');
    };
    let html = await openOne();
    if (!html) {
      await page.evaluate(() => document.querySelector('.marker-cluster')?.click());
      await page.waitForTimeout(1500);
      html = await openOne();
    }
    expect(html, 'no popup opened').toBeTruthy();
    expect(html).toMatch(/href="https:\/\//);
    expect(html).toContain('full details');
  });
});

// The site masthead is a <header>. Two tools styled the bare `header` element,
// which reached it: `display:flex` collapsed the wordmark block to its content
// width, so the 5/3/2 rule stopped a third of the way across the page, and
// noblogs additionally made the masthead sticky at z-index 600. Both now scope
// their rules to an id.
/* The same guard, for the promo band.
 *
 * The masthead check below exists because both tools once styled a bare
 * `header`. dsa-explorer was still styling a bare `aside` — and the band IS an
 * <aside>, rendered earlier in the DOM — so on that page only it picked up
 * padding:16px 16px 24px and a left border from the detail panel. Every other
 * page reported 0, which is what made it a leak rather than a design.
 *
 * `aside` is the second name in CLAUDE.md's list. `main` and `#panel` are the
 * other two; if one of those starts drifting, this is the shape of the test. */
test.describe('the promo band is not restyled by a tool', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  for (const path of ['/', '/noblogs/', '/dsa-explorer/', '/browse/', '/about/']) {
    test(`${path} leaves the band's own box alone`, async ({ page }) => {
      await page.goto(HOST + path, { waitUntil: 'domcontentloaded' });

      const band = await page.evaluate(() => {
        const el = document.querySelector('aside.w-full');
        if (!el) return null;
        const cs = getComputedStyle(el);
        return {
          padding: cs.padding,
          borderLeftWidth: cs.borderLeftWidth,
          gridColumn: cs.gridColumn,
        };
      });

      if (!band) return;              // banner disabled in _data/banner.yml
      expect(band.padding, 'a tool is padding the site banner').toBe('0px');
      expect(band.borderLeftWidth, 'a tool is bordering the site banner').toBe('0px');
    });
  }
});

test.describe('the masthead is not restyled by a tool', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  // Every page kind: the tools index, a tool that styles `header` (noblogs and
  // dsa-explorer both did), one that does not, and a narrative page.
  for (const path of ['/', '/noblogs/', '/dsa-explorer/', '/browse/', '/about/']) {
    test(`${path} keeps the masthead a plain block`, async ({ page }) => {
      await page.goto(HOST + path, { waitUntil: 'domcontentloaded' });

      const m = await page.evaluate(() => {
        const header = document.querySelector('header.page-column');
        // By its own hook. This was `div[aria-hidden="true"]` — "the first
        // decorative div in the header" — which silently became the nav's
        // phone scrim when the nav moved into the masthead. The scrim is
        // md:hidden, so the rule's width read as 0 at 1280px.
        const rule = header.querySelector('[data-masthead-rule]');
        const cs = getComputedStyle(header);
        const rs = getComputedStyle(rule);
        return {
          display: cs.display,
          position: cs.position,
          // The content box. clientWidth still includes the px-gutter padding,
          // and the rule is a child laid out inside it.
          headerInner: Math.round(
            header.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)
          ),
          ruleWidth: Math.round(rule.getBoundingClientRect().width),
          barTop: rs.borderTopWidth,
          gap: rule.clientHeight,
          barBottom: rs.borderBottomWidth,
          total: rule.offsetHeight,
        };
      });

      expect(m.display).toBe('block');
      expect(m.position).toBe('static');

      // The rule spans the container, not the width of the longest line.
      expect(m.ruleWidth).toBe(m.headerInner);

      // 5px bar, 3px gap, 2px bar. The height is the 10px total because
      // preflight sets border-box; asking for the 3px gap collapses it.
      expect(m.barTop).toBe('5px');
      expect(m.gap).toBe(3);
      expect(m.barBottom).toBe('2px');
      expect(m.total).toBe(10);
    });
  }

  /* The wordmark is an <h1> on the tools index and a <p> wrapping a link to
     `/` everywhere else, so the outline stays honest. While that was two
     copies of the same utilities the two drifted, and not visibly at the point
     of the mistake: main.css's `a { @apply font-semibold }` is 600 and applies
     to the <a> INSIDE the <p>, which is the element that renders the glyphs.
     The `font-bold` sat on the <p> and never reached them, so every page but
     the index drew the wordmark a weight light. One .dr-wordmark now; the
     variant is which tag, never which type. */
  test('the wordmark is the same type on every page', async ({ page }) => {
    const read = async (path) => {
      await page.goto(HOST + path, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector('.dr-wordmark', { timeout: 60000 });
      return page.evaluate(() => {
        const el = document.querySelector('.dr-wordmark');
        /* The element that actually PAINTS the text, which is the link when
           there is one. Reading the <p> is what hid the bug in the first
           place: it computed 700 while the <a> inside it rendered at 600. */
        const painted = el.querySelector('a') || el;
        const s = getComputedStyle(painted);
        return {
          weight: s.fontWeight, size: s.fontSize, spacing: s.letterSpacing,
          color: s.color, underline: s.textDecorationLine,
        };
      });
    };

    const home = await read('/');
    expect(home.weight).toBe('700');
    expect(home.underline).toBe('none');

    for (const path of ['/noblogs/', '/dsa-explorer/', '/about/', '/browse/']) {
      expect(await read(path), `${path} draws the wordmark differently`).toEqual(home);
    }
  });
});

// Every band of site chrome stops at the shell measure. The banner and the
// footer used to be full-bleed: on a window wider than the shell the yellow
// band ran edge to edge past a centered masthead, and the footer rule with it.
//
// The banner's COLOR is full-bleed again, deliberately — see the comment in
// _includes/banner.html. What is measured here is its content column, which is
// the thing that has to line up with the masthead.
test.describe('site chrome stops at the shell measure', () => {
  // Wider than --column-max, so the cap is actually exercised.
  test.use({ viewport: { width: 2000, height: 900 } });

  for (const path of ['/', '/noblogs/?view=dash', '/about/']) {
    test(`${path} caps the banner, masthead, content and footer together`, async ({ page }) => {
      await page.goto(HOST + path, { waitUntil: 'domcontentloaded' });

      const m = await page.evaluate(() => {
        const px = (el) => Math.round(el.getBoundingClientRect().width);
        const shell = parseFloat(
          getComputedStyle(document.documentElement).getPropertyValue('--column-max')
        ) * 16; // rem -> px
        const footer = document.querySelector('footer');
        const band = document.querySelector('aside[aria-label]');
        const banner = band && band.querySelector('.banner-bar');
        return {
          shell,
          header: px(document.querySelector('header.page-column')),
          main: px(document.querySelector('main')),
          banner: banner ? px(banner) : null,
          bandIsFullBleed: band ? px(band) === document.documentElement.clientWidth : null,
          footer: footer ? px(footer) : null,
          // Anything else painting wider than the shell. Fixed overlays are
          // meant to cover the viewport, #content is an unstyled wrapper, and
          // the banner's colored band is full-bleed on purpose.
          overflowing: [...document.querySelectorAll('body *')]
            .filter((el) => {
              const b = el.getBoundingClientRect();
              if (b.width <= shell + 1 || b.height === 0) return false;
              if (getComputedStyle(el).position === 'fixed') return false;
              if (band && el === band) return false;
              return el.id !== 'content';
            })
            .map((el) => el.tagName + (el.id ? '#' + el.id : '')),
        };
      });

      expect(m.header).toBe(m.shell);
      expect(m.main).toBe(m.shell);
      if (m.banner !== null) expect(m.banner).toBe(m.shell);
      if (m.bandIsFullBleed !== null) expect(m.bandIsFullBleed).toBe(true);
      if (m.footer !== null) expect(m.footer).toBe(m.shell);
      expect(m.overflowing, `wider than the shell: ${m.overflowing.join(', ')}`).toEqual([]);
    });
  }
});

// The shell is two numbers, picked by viewport: 1400px below 1600, 1600px from
// 1600 up. On a 1500px window the 1600px measure never got to cap anything, so
// the content filled the glass with only the 20px gutters either side.
//
// The widths are asserted literally rather than against --column-max, which is
// the value under test — reading it back would pass whatever it said.
test.describe('the shell measure follows the viewport', () => {
  for (const { width, shell } of [
    { width: 1280, shell: 1280 }, // narrower than 1400: the window is the cap
    { width: 1500, shell: 1400 },
    { width: 1599, shell: 1400 }, // last pixel below the breakpoint
    { width: 1600, shell: 1600 }, // the breakpoint itself is the wide measure
    { width: 2000, shell: 1600 },
  ]) {
    test(`a ${width}px window puts the content on a ${shell}px shell`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(HOST + '/', { waitUntil: 'domcontentloaded' });

      const m = await page.evaluate(() => {
        const px = (el) => Math.round(el.getBoundingClientRect().width);
        const band = document.querySelector('aside[aria-label]');
        return {
          header: px(document.querySelector('header.page-column')),
          main: px(document.querySelector('main')),
          banner: band ? px(band.querySelector('.banner-bar')) : null,
          // The color is not on the shell at any width.
          band: band ? px(band) : null,
          client: document.documentElement.clientWidth,
        };
      });

      expect(m.header).toBe(shell);
      expect(m.main).toBe(shell);
      if (m.banner !== null) expect(m.banner).toBe(shell);
      if (m.band !== null) expect(m.band).toBe(m.client);
    });
  }
});
