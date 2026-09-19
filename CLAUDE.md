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

Tests need the dev server running: `npx playwright test` (188 specs, ~42s).

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

## Deploying — read this before touching `docs/`

**`docs/` IS production. Do not delete it.** Verified 2026-09-18 by comparing
bytes and response headers:

- `datarepublican.com` is Cloudflare in front of **Coolify**, and what Coolify
  serves is byte-identical to `docs/` on `master`
  (`assets/css/styles.css` md5 `d2344d57…` on all three). Production responses
  carry **no** GitHub Pages headers (`etag`, `x-github-request-id`), so Pages is
  not the origin.
- `datarepublican.github.io/datarepublican/` is a **second, parallel** Pages
  deployment of the same content. Its Source is set to "GitHub Actions" but
  `master` has no workflow, so nothing can ever publish there — it is frozen on
  a Sep 3 artifact.
- Coolify also builds per-PR previews at `<PR#>.datarepublican.com`
  (`preview_url_template` is `{{pr_id}}.{{domain}}`). **Every preview deploy
  fails** — 27 of 27 — so the 526 that Cloudflare returns is a symptom: there is
  no container behind the hostname, not a certificate problem.

  The cause is in the build, and it is a Coolify bug, not a repo problem. The
  `static` build pack generates a small Dockerfile into the base directory and
  builds it. On a production deploy that works (`transferring dockerfile: 436B`).
  On a preview deploy the file is never written (`transferring dockerfile: 2B`,
  then `failed to read dockerfile: open Dockerfile: no such file or directory`),
  because `base_directory` is `/docs` rather than `/`. Production deploys are
  unaffected: all 8 have succeeded, the last on 2026-09-03.

So the live site is a committed build artifact. It is not stale because deploys
are broken — production deploys work fine and the last one matches `master`
exactly. It is stale because **nobody has regenerated `docs/` since 2026-08-31**,
and `master` has not moved since 2026-09-02. Coolify runs no build: its config is
`build_pack: static`, `base_directory: /docs`, no install/build/start command. It
copies `docs/` into `nginx:alpine` and serves it.

Consequences for anything you do here:

- `_config.yml` still says `destination: docs`, so a **bare `jekyll build` or
  `jekyll serve` with no `--destination` rewrites production's artifact.**
  Always go through the npm scripts, which pass `--destination _site`.
- Coolify's build configuration lives in its own UI, not in this repo. There is
  no Dockerfile, nixpacks config or compose file here. You cannot review or
  reproduce the deploy from the source tree.
- `.github/workflows/deploy.yml` exists on `redesign-v2` only. Merging it adds a
  *third* publishing path. Decide the architecture first.

After a deploy, verify by content: the domain returns 200 for any path, so a
status code proves nothing.

### Going live: the cutover runbook

The repo side of this is already done and sitting on this branch — `Dockerfile`,
`.dockerignore` and `deploy/nginx.conf` build the site from source instead of
serving `docs/`. Both halves are verified on real infrastructure (a throwaway
Coolify app built from `infra/dockerfile-build`): a production-style deploy and
a per-PR preview both succeeded and served the v2 chrome.

**Nothing is live until someone changes Coolify.** The order below matters;
each step is reversible, and step 4 is not.

1. **Merge this branch to `master`.** Production does not change — Coolify is
   still on `build_pack: static` reading `docs/`, and `docs/` is still there.
2. **Switch the production app** (`qw4koc0gkcwgs8wwckkcc8cc`) to:
   `build_pack: dockerfile`, `base_directory: /`, `dockerfile_location:
   /Dockerfile`. Reversible — set the fields back to `static` and `/docs`.
   This is the first deploy that publishes what `master` actually contains.
3. **Verify by content**, not status code. `/`, `/noblogs/`, `/dsa-explorer/`,
   `/browse/`, `/officers/bulk/`, `/about/`. Compare against the throwaway app
   if it still exists.
4. **Only then** `git rm -r docs/`, set `_config.yml`'s `destination` to
   `_site`, and drop `docs` from `exclude`. 426 MB and 10,011 files, and the
   "a bare `jekyll build` overwrites production" trap goes with them.

**GitHub Pages reads `master:/docs` too.** Step 4 breaks it. Decide before then
whether Pages stays; if it does, it needs its own source, and it should get a
`docs/.nojekyll` (it currently re-runs Jekyll over already-built HTML, which
Coolify does not).

Known and deliberate: `/nope-xyz/` returns **200**, not 404. `try_files $uri
$uri/ /index.html` in `deploy/nginx.conf` makes the `error_page 404` block dead
code. That is exactly what production does today and was reproduced on purpose
rather than changed mid-migration. Worth fixing as its own commit afterwards.

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
