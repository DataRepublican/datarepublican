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

Tests need the dev server running: `npx playwright test` (254 specs, ~85s).

## Access — how to reach the tools, so nobody re-derives this

**GitHub → use `gh`, not an MCP server.** It is installed and authenticated
(`repo`, `workflow`, `read:org`). The hosted GitHub MCP server cannot be
authorized from here — it fails with "Incompatible auth server: does not support
dynamic client registration" — so do not spend time on it.

```bash
gh api repos/DataRepublican/datarepublican/pages       # Pages config
gh pr view 68 --repo DataRepublican/datarepublican --json statusCheckRollup
gh run list --workflow=ci.yml
```

**Coolify → REST API with a token on disk.** Token at
`~/.config/coolify/token` (mode 600, outside the repo). Never echo it; read it
inline:

```bash
CB=https://datarepublican-coolify.americancloud.dev
T=$(cat ~/.config/coolify/token)
curl -s -H "Authorization: Bearer $T" "$CB/api/v1/applications"
```

Endpoints that exist and are worth knowing (Coolify 4.3.21):

| | |
|---|---|
| `/api/v1/version` | sanity check the token |
| `/api/v1/projects`, `/api/v1/applications` | inventory |
| `/api/v1/applications/{uuid}` | full build config for one app |
| `/api/v1/deployments/applications/{uuid}?take=40` | deploy history **and full build logs**, `pull_request_id` distinguishes previews |
| `/api/v1/applications/{uuid}/logs` | live nginx access log |

`/api/v1/deployments` (no app) only lists *in-flight* deployments and is
normally empty — the per-application endpoint above is the one you want.

The production app is `qw4koc0gkcwgs8wwckkcc8cc`.

⚠️ **The current token is not read-only.** `/api/v1/security/keys` returns
private SSH keys in plaintext. Treat the token as a full credential, prefer a
read-only one, and never call that endpoint.

**Cloudflare** sits in front of production. The `cloudflare-api` /
`cloudflare-observability` MCP servers are configured but unauthenticated, so
zone settings (SSL mode, DNS records, proxy status) are not readable from here
yet. Authorize via `/mcp` in an interactive session if that is needed.

## When a change does not show up

This repo has burned an afternoon on this more than once. Before you touch the
code again, work down this list — the source was correct every time.

1. **Did you change `_config.yml`?** Jekyll's `--incremental` never treats it as
   a dependency, and a restart alone *cannot* fix it: the restart reads the new
   config, sees every output file newer than its source, and skips the rebuild.
   `yarn start` clears `_site` and `.jekyll-metadata` first, which is the fix.
   Restart via `yarn start`, not `npm run jekyll:serve`.
2. **Did you change `postcss.config.js`?** The Tailwind watcher reads it once,
   at boot, and a long-running watcher keeps the old pipeline forever. This has
   already bitten: adding `postcss-import` made a manual `build:css` inline the
   `@import` correctly, then the stale watcher overwrote `styles.css` with the
   `@import` left as a literal at-rule. The browser fetched the raw
   `assets/css/tokens.css`, which is full of unprocessed `theme()` calls, so
   every `--dr-*` token silently evaluated to nothing and anything keyed off
   them lost its fill. **Restart with `yarn start`.** Detect it with
   `curl -s localhost:4000/assets/css/styles.css | grep -c '^@import'` — the
   answer is 0. `tailwind.config.js` does *not* have this problem; the CLI
   watches it.
3. **Did you add a new Tailwind class in HTML?** Check the rule exists:
   `curl -s localhost:4000/assets/css/styles.css | grep -F 'your-class'`.
   If it is missing, see the Liquid trap below.
4. **Is the output actually newer than the source?**
   `stat -f "%Sm %N" -t "%H:%M:%S" <source> _site/<output>`. A stale `_site`
   file reads exactly like a broken change.
5. **Is the viewport wide enough?** The shell caps at 1600px. On a narrower
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

**Ship an image at the size it is painted.** A 1024px PNG drawn into a 62px
circle passes every other spec here — it is on screen, in the right place, and
looks correct. `/ea-explorer/words/` shipped 12.7 MB of avatars that way and
the tools index 5 MB of screenshots. `tests/test_image_weight.spec.js` fails a
route that sends a file over 120 KB into a box less than a third its width, and
holds the tools index under a 2.5 MB image budget. Convert with Pillow (no
cwebp, ImageMagick or sharp here, and `sips` cannot write WebP on this macOS).

**Feature cards paint at 768px, standard cards at 438px** — `_data/tools.yml`'s
`feature: true` picks the shape, so the two want different source widths.

**Vendored libraries are shared, not copied per tool.** `assets/js/` holds the
two the shell and the redesigned tools load (jQuery 3.5.1, Cytoscape);
`assets/js/lib/` holds the rest, version-suffixed because two jszips and
two papaparses are both in use. Loaded per page, never from
`_includes/head-custom.html` — Cytoscape is 353 KB and four routes need it,
not 34. `noblogs/graph/` and the other standalone pages have no front matter,
so they cannot use `relative_url`; `baseurl` is `""`, so a root-absolute
`/assets/js/…` is what that filter would emit anyway.
`tests/test_vendored_libs.spec.js` fails on a re-duplicated library.

**Do not name a shared directory `vendor`.** `.gitignore` has a bare `vendor`,
and gitignore matches a bare name **at any depth** — `assets/js/vendor/` was
silently skipped by `git add -A` while the same commit deleted the 24 per-tool
copies it replaced. Everything built and every spec passed locally, because
the dev server reads the working tree; the files simply were not in the deploy.
`.dockerignore` and `_config.yml` carry the same bare `vendor`, for
`bundle install --path vendor/bundle`. The shared directory is `assets/js/lib/`
for that reason, and `tests/test_assets_committed.spec.js` fails on any
`/assets/…` reference that git is not tracking.

**A missing asset does not 404 in production.** `try_files $uri $uri/
/index.html` answers it with the home page, so a missing script reports
`Unexpected token '<'` and whatever it defined reports as undefined. Check
`content-type`, not the status code.

**`importScripts` resolves against the WORKER's URL, not the page's**
(`officers/unzipWorker.js` loads JSZip that way, and `officers/bulk/` runs it
from one directory up), and a grep for `<script src>` will not find it.

**`ea-explorer/words/data.json` cannot be split by chunking it.** The page
builds a reverse keyword index over every quote at boot (full text, gloss,
post title, author name), and `Q[qid]` is random access across the whole
corpus — the topics view previews each topic's lead quote, the people view
each author's top quote, and the author drawer renders every quote that
person has, up to 625. Splitting means precomputing the index at build time
and emitting per-author chunks, the way `data:split` already does for noblogs.
gzip takes it 6.18 MB -> 1.74 MB, which is most of the win for none of the risk.

**`flex: 0 0 auto` on anything whose width comes from data will overflow.** A
flex item that cannot shrink keeps its max-content width however narrow the
column is, and `min-width: 0` is needed as well, because a flex item's default
`min-width: auto` floors it at min-content. Both overflows on the EA pages were
this: a relationship label out of `edges.csv` in the detail panel, and the
header's row of links. Reserve `0 0 auto` for fixed chrome — a dot, an arrow, a
badge.

**Horizontal overflow hides twice.** Inside `.dr-sheet__body` it is contained
by that element's `overflow-x: auto`, so the panel scrolls and the document
measures correct — a document-level check never sees it. On a phone it does not
scroll at all: the layout viewport widens, `innerWidth` comes back larger than
the device, and every other measurement is then taken against a viewport that
does not exist. `tests/test_no_x_overflow.spec.js` measures the document at
390px and the panel on its own.

**The EA section uses extensionless URLs**: `/ea-explorer/tour/`,
`/ea-explorer/words/`, `/ea-explorer/network/`. The tour and the network set a
`permalink`, so their assets are root-absolute — a directory URL resolves
`data/…` one level deeper than a `.html` URL did, and the logo manifest stores
paths relative to `/ea-explorer/`, so `LOGO_BASE` prefixes them. The old
`.html` paths are kept alive with `redirect_from`.

**Preflight sets `box-sizing: border-box`.** A rule built from `border-t` +
`height` + `border-b` needs the height to be the *total*, not the gap.

## Layout

- **One shell for every page**: `.page-column`, 1600px, from `--column-max` on
  `:root`. There is no per-page width setting — the chrome must not change size
  between pages. The banner and footer take `.page-column` too.
- **Reading measures belong to the content**, not the page: `.text-column`
  (832px) on `/about/` and `/donate/`, `.prose max-w-column` in the markdown
  layout. Anything that should line up with that text takes `max-w-prose`.
- **The nav is included by `_includes/masthead.html`, inside the wordmark row.**
  It used to be a sibling of `<header>` so it could be sticky at md — a sticky
  element can only travel inside its parent's box, and inside the masthead that
  box is ~130px tall. Desktop gave up stickiness deliberately, in exchange for
  plain links sitting across from the wordmark. The phone pill is
  `position: fixed`, so it does not care what contains it and did not change.
  Do not re-add `{% include nav.html %}` to the layouts; it renders twice.
- **Nav sizing is anchored to the 16px label** and expressed in `em`. The 44px
  tap target applies on phones only.
- `_data/tools.yml` is the single source of truth for the tools index.
- **Tool chrome has a pattern, and it is written down.** One row per question,
  nothing permanent on the canvas, legal text in a modal. Read
  `.claude/skills/dr-design-system/references/tool-chrome.md` before laying out
  a tool header or putting anything on top of a map or a graph. `noblogs` and
  `dsa-explorer` both follow it.

## Deploying

**Production is Coolify**, at `datarepublican.com`, behind Cloudflare. It builds
from source with this repo's `Dockerfile` and serves `_site` out of
`nginx:alpine` using `deploy/nginx.conf`.

**Push to `master` and it deploys.** There is no manual step and nothing to
commit into `docs/`. Cutover happened 2026-09-22 (merge `5412172a`); before
that, production served the committed `docs/` directory and had been frozen on
an Aug 31 build.

| | |
|---|---|
| app uuid | `qw4koc0gkcwgs8wwckkcc8cc` |
| build pack | `dockerfile`, `base_directory: /`, `dockerfile_location: /Dockerfile` |
| branch | `master` |
| previews | `pr-{{pr_id}}.datarepublican-site.americancloud.dev` |

Things that follow from this, and have already cost time once each:

- **Any push to `master` rebuilds production**, including a README-only commit —
  `watch_paths` is unset. Harmless, just slow (the build is several minutes,
  most of it `bundle install`).
- **`health_check_enabled` is false**, so the container swap is not gated on the
  new container being ready. The build completes first, so the exposed window is
  the swap itself — seconds — but it is not strictly zero-downtime.
- **The build resolves gems from scratch every time.** `Gemfile.lock` is
  gitignored, so the Dockerfile copies `Gemfile` only; copying the lock would
  fail the build outright in a fresh clone. `github-pages` pins the transitive
  set, which is what stops that drifting.
- **Rolling back is a config change, not a revert.** `docs/` is still on `master`
  and still what GitHub Pages serves, so:

      curl -X PATCH -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
        -d '{"build_pack":"static","base_directory":"/docs"}' \
        "$CB/api/v1/applications/qw4koc0gkcwgs8wwckkcc8cc"

  That restores the pre-cutover site exactly. It stops being available the day
  `docs/` is deleted.

### Verify by content, never by status code

    scripts/verify-deploy.sh https://datarepublican.com <git-ref>

Five checks: the route contract, every referenced asset's content-type, gzip,
`og.png` byte-identical to the ref, and the v2 chrome present. Run it after a
deploy. Three traps it exists to defeat — each one makes a broken deploy look
fine, or a fine deploy look broken:

1. **`try_files $uri $uri/ /index.html` answers a missing asset with the home
   page, at 200.** A missing script reports `Unexpected token '<'` and whatever
   it defined reports as undefined. Check `content-type`, not the status code.
2. **`url:` in `_config.yml` is always `https://datarepublican.com`**, so
   jekyll-seo-tag emits absolute production URLs from *every* environment.
   Following `og:image` off a staging host measures production and reports the
   environment you are actually testing as broken.
3. **`/ea-explorer/network.html` and `/ea-explorer/words/opener.html` are
   `jekyll-redirect-from` stubs** that redirect to production from everywhere.
   Excluded from the sweep on purpose.

Also confirm gzip: it comes from `deploy/nginx.conf`, and Coolify's own
`custom_nginx_configuration` stops applying under the dockerfile build pack.

### `docs/` is no longer production, but it is not dead yet

It is **still what GitHub Pages serves**, and still the rollback surface.

    gh api repos/DataRepublican/datarepublican/pages
    build_type  legacy
    source      {branch: master, path: /docs}

Pages is on the *legacy branch build* reading `master:/docs`, and it rebuilds on
every push to `master`. It is a second, independent publisher —
`datarepublican.github.io/datarepublican/` — and it shows the old site, because
`docs/` has not been regenerated since Aug 31. That is expected, not a symptom.

`.github/workflows/deploy.yml` was deliberately **not** merged (removed in
`e88f1ae2`). It published `_site` to Pages on every push to `master`; against a
`legacy` site it either fails outright or silently converts a public site's
publishing source as a side effect of an unrelated merge. If it is ever wanted,
Pages needs `build_type=workflow` first, or the workflow needs
`enablement: true` on `configure-pages`. It is recoverable from history.

**Before deleting `docs/`** (445 MB, 10,011 files), decide what Pages is for.
Deleting it breaks Pages and removes the config-only rollback. The rest of the
cleanup is: `git rm -r docs/`, set `_config.yml`'s `destination` to `_site`, drop
`docs` from `exclude` — and the "a bare `jekyll build` overwrites production"
trap goes with it.

Known and deliberate: `/nope-xyz/` returns **200**, not 404, because `try_files`
makes `deploy/nginx.conf`'s `error_page 404` block dead code. That is what
production did before the cutover and was reproduced on purpose rather than
changed mid-migration. Worth fixing as its own commit.

## House style

American English in code comments, commit messages and user-facing copy.

### Comments: mechanics and traps, not design rationale

A comment earns its place when the code would otherwise **look wrong**, or when
something off-screen will **break it**. Everything else is noise, and noise is
expensive: it buries the four or five comments in a file that are actually
load-bearing.

**Write a comment for:**

- a trap with a cost — `:not([hidden])` beating the UA rule, `isolation` over a
  vendored z-index, a class glued to a Liquid tag, `--nb-header-h` being a
  height and not an offset
- a line that looks redundant but is not — "everything before `cursor` undoes
  the global `button` rule"
- a constraint from somewhere else in the system — "the standalone page still
  ships this", "a spec asserts this id", "16px or iOS zooms and never unzooms"
- a number nobody could re-derive — where `340px` comes from

**Do not write a comment for:**

- why a design decision is good. "A reset next to a title only ever means one
  thing", "three ragged pills read as an afterthought", "the map is the thing
  the tool is for." If it argues taste, cut it.
- the change's own history. "This used to be X, then Y, now Z." Nobody reading
  the file needs the narrative; that is what `git log` and the commit message
  are for. The *conclusion* can stay if it is a trap ("do not go back to
  reading this from the DOM — deleting the legend silently blanks it").
- what the code plainly says. `display:flex` does not need a sentence.

The test: **delete it and ask whether the next person breaks something.** No →
it should not be there. Design intent belongs in
`.claude/skills/dr-design-system/`, not inline — it is written once there and
read by everyone, instead of once per declaration.

Match the density in `_includes/nav.html` and the top of `assets/css/main.css`.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill
tool. When in doubt, invoke the skill. These are gstack's `g-`-prefixed names
(see the global CLAUDE.md for why the prefix exists).

- Product ideas/brainstorming → `/g-office-hours`
- Strategy/scope → `/g-plan-ceo-review`
- Architecture → `/g-plan-eng-review`
- Design system/plan review → `/g-design-consultation` or `/g-plan-design-review`
- Full review pipeline → `/g-autoplan`
- Bugs/errors → `/g-investigate`
- QA/testing site behavior → `/g-qa` or `/g-qa-only`
- Code review/diff check → `/g-review`
- Visual polish → `/g-design-review`
- Ship/deploy/PR → `/g-ship` or `/g-land-and-deploy`
- Save progress → `/g-context-save`
- Resume context → `/g-context-restore`
- Author a backlog-ready spec/issue → `/g-spec`
