# Traps

Each has cost real time here. Reproduction, then the command that detects it.

## 1. Tailwind purges a layered rule it cannot find

**What happens.** A plain CSS rule inside `@layer components` is dropped unless
Tailwind finds its selector in scanned HTML. Every `.dr-*` class is created at
runtime by JS, so none of them survive inside a layer.

**How it showed up.** `.dr-canvas` and `.dr-controls` vanished entirely.
`.dr-sheet__grip` kept its mobile rules but lost the base `display: none`, so the
drag handle appeared on desktop.

**Rule.** Anything in `assets/css/components/` is outside a layer, by convention,
so nobody has to remember. Same for `tokens.css` — `:root` is not a class.

```sh
curl -s localhost:4000/assets/css/styles.css | grep -F 'dr-sheet__grip'
```

## 2. A class glued to a Liquid tag is swallowed

**What happens.** Tailwind scans the raw file. A class written immediately after
a closing Liquid tag with no space becomes one candidate together with that tag,
matches no utility, and the rule is never generated. Fails silently.

**Fix.** Assign classes to a variable and interpolate, so every class sits inside
a quoted string. See `_includes/nav.html`.

```sh
curl -s localhost:4000/assets/css/styles.css | grep -F 'your-class'
```

## 3. A tool styles a bare element and reshapes the site

**What happens.** The site masthead is a `<header>` and precedes the tool's own in
the DOM; the promo band is an `<aside>`; the layout has a `<main>`. A tool
styling any of them bare reaches across the page.

**How it showed up, twice.** noblogs styled bare `header`, turned the masthead
into a flex container and made it sticky at z-index 600; its
`querySelector('header')` also returned the masthead, so the measured header
height was the wrong element's. Then dsa-explorer was found styling bare
`aside` — 26 rules of it — and the promo band IS an `<aside>`, so on that page
only it carried `padding:16px 16px 24px` and a left border. Both are fixed.

`main` and `#panel` are the two names left on the list.

**Guarded by** `tests/test_review_regressions.spec.js`, which checks the
masthead AND the banner across five page kinds. Verify a guard like that by
restoring the bare selector and watching it fail on exactly the one page.

## 4. A vendored z-index competes in a stacking context you did not mean to share

**What happens.** Leaflet numbers its panes 400 / 800 / 1000, assuming it owns a
stacking context. `#mapwrap` is `position: relative` with no `z-index` and
`#mapcanvas` is `position: absolute` with no `z-index` — **neither creates one**.
So the panes are painted in the nearest ancestor that does.

**Where that actually is, measured.** Not the root. `_layouts/default.html` gives
`<main>` the `@container` class, and `container-type: inline-size` establishes a
stacking context (and a containing block for fixed-position descendants). So the
real contest was *inside* `<main>`: Leaflet's map pane at **400** against
`.dr-sheet` at **60**. The pane won.

> Verified with a DOM walk, after an earlier "they escape to the root" diagnosis
> turned out to be wrong. The fix is the same either way, but the mechanism is
> not — and `container-type` creating a stacking context is the kind of thing
> that will bite again somewhere else in this layout.

**How it showed up.** The mobile detail sheet rendered *under* the map. On
desktop, Leaflet's zoom control floated over the open drawer, uncovered by its
scrim.

**Fix.** `isolation: isolate` on the canvas wrapper, which gives Leaflet the
context it already assumed it had.

**Isolate the vendor's OWN container too, not just the wrapper.** Doing only the
wrapper fixes the page but breaks the tool's own chrome, and that shipped:
`#mapcanvas` is `position:absolute` with `z-index:auto`, so Leaflet's panes were
hoisted exactly one level and competed *inside* `#mapwrap` against the info card
at 20. `.leaflet-top` is 1000, so it won, and the card carrying the map's
category filters stopped receiving clicks — `elementFromPoint` over it returned
`canvas.leaflet-zoom-animated`. Both `#mapwrap` and `#mapcanvas` carry
`isolation: isolate` now.

The general rule: **contain at the element the vendor writes into.** One level
of containment moves the problem rather than solving it.

**And never isolate a box that contains the sheet.** The same commit added
`isolation: isolate` to `#graphouter` for consistency, and `#graphouter`
contains `#gpanel` — which DRSheet turns into a `position: fixed` sheet on a
phone. That scoped the sheet's z-60 *inside* the box while its scrim, appended
to `document.body` at z-55, stayed outside it. The scrim then covered its own
sheet and swallowed every tap on the close button. The map is unaffected because
its sheet wraps `#panel`, a sibling of `#mapview` rather than a child of
`#mapwrap`.

So: isolate the canvas, never an ancestor of the detail panel. Before adding
`isolation` anywhere, ask what `position: fixed` descendants the box has.

And never out-bid — that is how you get a 1200 and then a 9999. noblogs was
already running 600/850/900/1000/1100/1150/1200 and the sheet was *still*
underneath.

**Test it by what a thumb hits, not by the numbers** — the bug was invisible from
the numbers, and so was a bad test of it. `tests/test_stacking.spec.js` samples
inside the **measured intersection** of the sheet and the canvas, and fails if
there is no intersection:

```js
const top = Math.max(sheet.top, map.top);
const bottom = Math.min(sheet.bottom, map.bottom, innerHeight);
// sampling just below the sheet's top edge is WRONG: at 390px the tool header
// pushes the map to y≈559 while the half-detent sheet starts at y≈380, so that
// point lands in the tab strip and the test passes with the fix reverted.
document.elementFromPoint(x, (top + bottom) / 2).closest('.dr-sheet')
```

**Always confirm a regression test fails without the fix.** This one did not, at
first, and would have shipped green over a live bug.

## 5. `docs/` is production

`_config.yml` says `destination: docs`, and `docs/` is what Coolify serves. A
bare `jekyll build` or `jekyll serve` **overwrites the live site**. Always go
through the npm scripts, which pass `--destination _site`.

## 6. `--incremental` hides a `_config.yml` change

A restart cannot fix it: the restart reads the new config, sees every output file
newer than its source, and skips the rebuild. `yarn start` clears `_site` and
`.jekyll-metadata` first, which is the fix. Restart via `yarn start`, never
`npm run jekyll:serve`.

## 7. A stale artifact reads exactly like a broken change

The chronic failure here. Correct source, stale output. Check the artifact:

```sh
curl -s localhost:4000/assets/css/styles.css | grep -F 'your-class'
stat -f "%Sm %N" -t "%H:%M:%S" <source> _site/<output>
```

## 8. `postcss-import` is present but not applied

It was in `node_modules` only because Tailwind depends on it, and **neither
build path applied it**: `build:css` runs `postcss` directly, and `watch:css`
passes `--postcss`, which replaces the CLI's built-in pipeline. Now listed
explicitly in `postcss.config.js` and `package.json`.

```sh
curl -s localhost:4000/assets/css/styles.css | grep -c '^@import'   # must be 0
```

## 8b. …and a running watcher keeps the old `postcss.config.js` forever

**This one actually shipped broken for an hour.** The Tailwind watcher reads
`postcss.config.js` once, at boot. Adding `postcss-import` to it while the
server was already running changed nothing for that process:

1. a manual `build:css` picked up the new config and inlined the tokens — which
   is what made it look verified
2. the stale watcher then rebuilt `styles.css` on the next edit, with the old
   pipeline, leaving `@import "./tokens.css"` as a literal at-rule
3. the browser fetched the **raw source** `assets/css/tokens.css`, which is full
   of unprocessed `theme('colors.accent')` calls
4. every `--dr-*` token evaluated to nothing, and everything keyed off them —
   the segmented control's fill, the tinted chips — silently lost its styling

Nothing errored. The page just looked wrong in a way that reads exactly like a
browser cache.

**Restart with `yarn start` after touching `postcss.config.js`.**
`tailwind.config.js` does not have this problem; the CLI watches it.

The general lesson, and the reason this is worth its own entry: **verifying a
build change with a one-off command proves the config, not the running system.**
Check the served artifact, and check it again after the watcher has rebuilt.

## 9. Another agent can reset your working tree

This repo is worked by more than one agent. Uncommitted work has been destroyed
twice by a `git reset` and a branch switch from a concurrent session. Commit
early, or work in a `git worktree`. Check `git branch --show-current` before
assuming which branch you are on.
