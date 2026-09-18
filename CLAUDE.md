# DataRepublican

A Jekyll site with Tailwind, built and deployed by GitHub Actions. `README.md`
is the long-form reference; this file is the short version plus the traps that
have actually cost time.

## Running it

```bash
yarn start          # then open http://localhost:4000
```

That is the only supported way to run the dev server. It cleans, creates the
directories the watcher has to ignore, splits the NoBlogs data, builds the CSS,
starts the Tailwind watcher and serves to `_site` — in that order, and every
step is load-bearing. Do not hand-roll `jekyll serve`.

- **No livereload.** Refresh by hand.
- **First boot takes ~20s** (data split + full build). It is not hung.
- **Never run `npm run build:css` while the server is up.** Two processes write
  `assets/css/styles.css` and a request can catch it mid-write.

Tests need the dev server running: `npx playwright test` (71 specs, ~35s).

## When a change does not show up

This repo has burned an afternoon on this more than once. Before you touch the
code again, work down this list — the source was correct every time.

1. **Did you change `_config.yml`?** Jekyll's `--incremental` never treats it as
   a dependency, and a restart alone *cannot* fix it: the restart reads the new
   config, sees every output file newer than its source, and skips the rebuild.
   `yarn start` clears `_site` and `.jekyll-metadata` first, which is the fix.
   Restart via `yarn start`, not `npm run jekyll:serve`.
2. **Did you add a new Tailwind class in HTML?** Check the rule exists:
   `curl -s localhost:4000/assets/css/styles.css | grep -F 'your-class'`.
   If it is missing, see the Liquid trap below.
3. **Is the output actually newer than the source?**
   `stat -f "%Sm %N" -t "%H:%M:%S" <source> _site/<output>`. A stale `_site`
   file reads exactly like a broken change.
4. **Is the viewport wide enough?** The shell caps at 1600px. On a narrower
   window content filling the screen is correct, not a bug.

## Traps

**Tailwind cannot see a class glued to a Liquid tag.** A class written
immediately after a closing Liquid tag, with no space, is swallowed into one
candidate with that tag and no rule is generated. Assign the classes to a
variable and interpolate it, so each class sits inside a quoted string. See
`_includes/nav.html`. Fails silently.

**A tool must not style bare `header`, `aside`, `main` or `#panel`.** The site
masthead is a `<header>` and it precedes the tool's own in the DOM. `noblogs`
and `dsa-explorer` both styled bare `header` and reshaped the masthead from
across the page; noblogs' `querySelector('header')` also returned the masthead,
so its measured header height was the wrong element's. Scope tool CSS and tool
JS to an id (`#nb-header`, `#dsa-header`).

**Anything written into the repo while the server runs triggers a rebuild**, and
pages 404 for the second or two it takes. Jekyll does not read `.gitignore`, and
its watcher does not skip dot-directories. `.gstack`, `test-results` and
`playwright-report` are in `_config.yml`'s `exclude`. That is necessary but not
sufficient: the watcher only ignores an excluded path that **exists when the
server boots**, which is why `start` mkdirs the two Playwright directories.

**`@layer components` rules get purged if Tailwind cannot find the selector in
the scanned HTML.** Anything whose class is created at runtime by JS, or is a
bare element selector, belongs *outside* the layer. `assets/css/main.css` says
which blocks and why.

**Preflight sets `box-sizing: border-box`.** A rule built from `border-t` +
`height` + `border-b` needs the height to be the *total*, not the gap.

## Layout

- **One shell for every page**: `.page-column`, 1600px, from `--column-max` on
  `:root`. There is no per-page width setting — the chrome must not change size
  between pages. The banner and footer take `.page-column` too.
- **Reading measures belong to the content**, not the page: `.text-column`
  (832px) on `/about/` and `/donate/`, `.prose max-w-column` in the markdown
  layout. Anything that should line up with that text takes `max-w-prose`.
- **The nav is a sibling of `<header>`, not a child.** A sticky element can only
  travel inside its parent's box.
- **Nav sizing is anchored to the 16px label** and expressed in `em`. The 44px
  tap target applies on phones only.
- `_data/tools.yml` is the single source of truth for the tools index.

## Deploying

Merge to `master`; Actions builds and uploads `_site`. `docs/` is a committed
445MB build output from before the Pages cutover — **it is not served**, and
`README.md` has the steps to finish removing it. Do not regenerate it.

After a deploy, verify by content: `datarepublican.com` returns 200 for any
path, so a status code proves nothing.

## House style

American English in code comments, commit messages and user-facing copy.
Comments should say *why*, especially where the obvious thing is wrong —
match the density already in `_includes/`, `_layouts/` and `assets/css/main.css`.
