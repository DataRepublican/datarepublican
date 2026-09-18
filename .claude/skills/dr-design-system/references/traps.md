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

**How it showed up.** noblogs styled bare `header`, turned the masthead into a
flex container and made it sticky at z-index 600; its
`querySelector('header')` also returned the masthead, so the measured header
height was the wrong element's. dsa-explorer still styles bare `aside`, so on
that page only, the promo band picks up `padding:16px 16px 24px` and a left
border. It already carries `id="panel"` — the fix is mechanical.

**Guarded by** `tests/test_review_regressions.spec.js` across five page kinds.

## 4. Vendored z-index escapes into the root stacking context

**What happens.** Leaflet numbers its panes 400 / 800 / 1000, assuming it owns a
stacking context. `#mapwrap` is `position: relative` with no `z-index` and
`#mapcanvas` is `position: absolute` with no `z-index` — **neither creates one**.
So every Leaflet pane competes in the root context against the site's layers.

**How it showed up.** The mobile detail sheet (z 60) rendered *under* the map.
On desktop, Leaflet's zoom control (z 1000) floated over the open drawer (z 900),
uncovered by its scrim.

**Fix.** `isolation: isolate` on the canvas wrapper. Never out-bid — that is how
you get a 1200 and then a 9999. noblogs was already running
600/850/900/1000/1100/1150/1200 and the sheet was *still* underneath.

```js
// the real question is what a thumb hits, not what a number says
document.elementFromPoint(x, y).closest('.dr-sheet')
```

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

It is in `node_modules` only because Tailwind depends on it, and **neither build
path applies it**: `build:css` runs `postcss` directly, and `watch:css` passes
`--postcss`, which replaces the CLI's built-in pipeline. Without adding it
explicitly, `@import` statements pass through as literal at-rules — nine
stylesheets fetched in series, working in dev, waterfalling in production.

```sh
curl -s localhost:4000/assets/css/styles.css | grep -c '@import'   # must be 0
```

## 9. Another agent can reset your working tree

This repo is worked by more than one agent. Uncommitted work has been destroyed
twice by a `git reset` and a branch switch from a concurrent session. Commit
early, or work in a `git worktree`. Check `git branch --show-current` before
assuming which branch you are on.
