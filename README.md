---
title: How to run the site locally
---

## Prerequisites

1. Install Ruby 3.1.4

   The version is pinned in `.ruby-version`. Newer Rubies will not work — the
   `github-pages` gem chain expects 3.1.x.

   ```bash
   rbenv install 3.1.4
   ```

2. Make sure rbenv is active in your shell

   This is the most common setup problem. `rbenv init` writes to `~/.zprofile`,
   which zsh only loads for **login** shells — so an integrated terminal in your
   editor can silently fall back to system or Homebrew Ruby. Put the init line in
   `~/.zshrc` instead, so it loads in every interactive shell:

   ```bash
   echo 'eval "$(rbenv init - zsh)"' >> ~/.zshrc
   ```

   If you append that line with `>>`, check that it landed on its own line —
   if your `~/.zshrc` had no trailing newline it will be glued onto the previous
   line and silently do nothing.

   Open a new terminal and verify from inside the project directory:

   ```bash
   ruby -v      # must print 3.1.4 — not 3.4, not 4.x
   which ruby   # must be a path under ~/.rbenv/shims
   ```

   If `which ruby` points at `/opt/homebrew/bin/ruby` or `/usr/bin/ruby`, stop
   here and fix it. Every step below will fail in confusing ways otherwise.

3. Install Bundler 2.x

   ```bash
   gem install bundler -v '~> 2.3'
   ```

   Do **not** run a bare `gem install bundler`. That installs Bundler 4.x, which
   requires Ruby >= 3.2 and cannot run on this project's Ruby.

   You do not need to install Jekyll separately — it comes from the
   `github-pages` gem, which pins it to the version GitHub Pages actually runs.

4. Install Node.js and yarn

   Node 22 LTS is known good.

   ```bash
   npm install --global yarn
   ```

## Setup

Install project dependencies:

```bash
bundle install    # Install Ruby dependencies
yarn install      # Install Node.js dependencies
```

## Run the site locally

```bash
bundle install     # Ruby deps (once)
yarn install       # Node deps (once)
yarn start         # then open http://localhost:4000
```

`yarn start` does three things in order:

1. **Splits the NoBlogs data** (`scripts/split-noblogs-data.mjs`). `/noblogs`
   fetches `data.index.json` and `data.detail.json`, which are generated from
   `data.json` and gitignored. Skip this and `/noblogs` 404s both files.
2. **Watches the CSS.** Jekyll does not run PostCSS, so without this the
   Tailwind stylesheet never rebuilds as you edit.
3. **Serves the site to `_site`** with livereload.

Running a piece on its own:

| | |
|---|---|
| `npm run data:split` | regenerate the NoBlogs index/detail files |
| `npm run watch:css` | Tailwind watcher only |
| `npm run jekyll:serve` | server only (assumes the two above have run) |
| `npm run build` | one-shot production build into `_site/` |
| `npm run serve:build` | serve what `npm run build` produced |

**The dev server no longer touches `docs/`.** It used to write there — that is
what the old "run `git restore docs/` before you commit" warning was about — and
it now builds to `_site` like everything else. If you ever see `docs/` dirty in
`git status`, something ran a bare `jekyll build`/`jekyll serve` without
`--destination`; recover with:

```bash
git checkout -- docs/ && git clean -fd docs/
```

> `_config.yml` still says `destination: docs` and that is deliberate — Jekyll
> excludes whatever that names from the *source scan*, which is what keeps the
> 632 MB committed tree from being read as source. The `--destination _site` on
> the command line is what decides where output actually goes. Changing the
> config value instead makes a build start rewriting `docs/`. It goes away when
> `docs/` does.

## Promoting to production

Deployment is automatic: **merge to `master` and GitHub Actions builds and
publishes.** There is no manual build step and nothing to commit into `docs/`.

`.github/workflows/deploy.yml` runs two gates before anything uploads:

- **Size.** The build is ~449 MB against a 1 GB GitHub Pages ceiling. It fails
  with a message naming the cause rather than at upload time with an opaque one.
- **The route contract.** `tests/routes.txt` lists every published URL; a build
  whose routes differ never reaches production. Removing a page deliberately
  means editing that file in the same commit, so it shows up in review.

`.github/workflows/ci.yml` runs the same build plus the full test suite on every
pull request.

### After a deploy, verify by content — not by status code

`datarepublican.com` returns **200 for any path**, including ones that do not
exist, so "it returns 200" proves nothing. Open the pages and look:

`/` &middot; `/noblogs/` &middot; `/dsa-explorer/` &middot; `/browse/` &middot; `/officers/bulk/` &middot; `/about/`

### Finishing the cutover (one time)

Pages **Source** is already set to *GitHub Actions*. Two steps remain:

1. Merge the redesign branch, then confirm a deploy serves the live site.
2. Remove `docs/` from git (10,011 files, 632 MB) and set
   `_config.yml`'s `destination` to `_site`.

Until step 2, `docs/` is dead weight: committed, and no longer what is served.
Rollback at any point is **Settings &rarr; Pages &rarr; Source &rarr; `master /docs`**.

## What is generated, and when to regenerate it

Most of the site is committed source. Four things are not, and two of them need
a manual run after the data pipeline drops new files in.

**Generated on every build — never commit these:**

| | |
|---|---|
| `_site/` | the built site |
| `noblogs/data.index.json`, `noblogs/data.detail.json` | split from `data.json` |
| `assets/css/styles.css` | Tailwind output (committed today, regenerated by the build) |

**Generated by hand, and committed** — re-run after the pipeline drops new
artifacts, or the site keeps showing the old ones:

```bash
node scripts/extract-logo-blobs.mjs   # after new *.embed.js logo blobs land
node scripts/capture-previews.mjs     # home page card images (needs a running server)
```

`extract-logo-blobs.mjs` turns `dsa-explorer/logos/*.embed.js` and
`noblogs/graph/logos.embed.js` — base64 PNG loaded as blocking scripts — into
image files plus a small manifest. Base64 does not compress, so those were 21 MB
and 12.6 MB *on the wire*. The `.embed.js` files stay in the repo as the
pipeline's artifacts and are excluded from the build in `_config.yml`.

### The data pipeline's side of the contract

The heavy datasets are built elsewhere and dropped into this repo. **Nothing
about that changes.** `noblogs/data.json` in particular is consumed exactly as
delivered — the split happens here, at build time, so there is no chunking
convention for the pipeline to honour. If `data.json` grows a field, it lands in
the index untouched and the build still passes.

Two gates run on every build and will stop it rather than ship bad data:

- **Redaction.** 291 doxxing-flagged blogs must carry no link fields; baselines
  are pinned at 291 blogs / 1,926 news entries / 515 quotes, all at zero links.
- **Reconstruction.** `data.index.json` + `data.detail.json` must reassemble
  `data.json` exactly.

## Housekeeping

`git status` should be clean after a dev session. If it is not:

| you see | what it is | what to do |
|---|---|---|
| `docs/` modified or deleted | something ran a build without `--destination` | `git checkout -- docs/ && git clean -fd docs/` |
| `_site/`, `test-results/`, `playwright-report/`, `.jekyll-metadata` | build and test output | gitignored; delete freely |
| `noblogs/data.index.json` / `data.detail.json` | the split output | gitignored; regenerate with `npm run data:split` |
| `assets/css/styles.css` modified | Tailwind rebuilt it | commit it if you changed CSS, otherwise `git checkout --` it |

Before opening a PR:

```bash
npm run build                                   # must be warning-free
python3 -m http.server 4000 --directory _site &  # a plain static server
npm run test:routes                             # all 34 routes resolve
npm test                                        # Playwright
git status                                      # clean, and no docs/ changes
```

## Testing

Serve the build with a **plain static server**. `npx serve` is not equivalent:
it rewrites `/officers/index.html` to `/officers`, dropping the trailing slash,
so relative script tags resolve against `/` and the page 404s its own
dependencies. GitHub Pages keeps the trailing slash.

The suite covers the usual page-loads-and-has-a-title checks, plus:

- **Mobile reachability** (`test_dsa_explorer_mobile`, `test_noblogs_mobile`) —
  controls present, &ge;44px, and *not occluded* at 390px. A tool can load fine
  and return correct data while being unusable with a thumb.
- **The tools index** (`test_tools_index`) — every entry in `_data/tools.yml`
  resolves, and each sort actually reorders. Read by *visual* order, since the
  sorting is CSS `order` and DOM order would pass regardless.
- **Payload regressions** — no `*.embed.js` logo blob is loaded,
  `quotes.embed.js` is fetched once rather than twice, `/noblogs` paints from
  the index without fetching `data.json`.
- **Controls that a refactor can silently kill** (`test_review_regressions`) —
  a selector left pointing at a renamed element leaves the page rendering
  perfectly with a dead control, which nothing else here would catch.

Use real clicks in new specs, not dispatched `MouseEvent`s. A synthetic event
goes straight to its target and cannot be intercepted, so it passes happily
while an invisible overlay eats every tap a real thumb makes.

## How the site is put together

- **Chrome** — `_layouts/default.html` is banner &rarr; masthead &rarr; nav
  &rarr; content &rarr; footer. One DOM order for both layouts; the nav pill is
  `fixed` at the bottom on a phone and `static` under the wordmark at `md`.
  `_data/banner.yml` drives the site-wide band; `enabled: false` removes it
  everywhere.
- **The tools index** — `/` is the tools page, which is why the nav has no Home
  item. `_data/tools.yml` is the single source of truth for all thirteen tools.
  `updated` is the last commit touching that tool's directory, so the default
  "Latest" sort means something; keep it honest.
- **Compact chrome** — tool pages get a one-line masthead and a shorter banner
  by default; the five narrative pages opt out in `_config.yml`.
- **Bottom sheets** — `assets/js/sheet.js`. On a phone, a tool's detail panel
  becomes a sheet over the canvas instead of a column 700px below the fold. At
  &ge;768px it is `display: contents` and the panel is an ordinary side column.
  Its styles live *outside* `@layer components` in `assets/css/main.css`,
  because Tailwind purges layer CSS whose classes never appear in any HTML —
  and every class there is created at runtime.

## Troubleshooting

**`jekyll: command not found`**

1. Confirm `ruby -v` prints 3.1.4 — see Prerequisites step 2
2. Confirm `gem list bundler` includes a 2.x version
3. Run `bundle install`
4. Run Jekyll through Bundler: `bundle exec jekyll ...`, never bare `jekyll`

**`cannot load such file -- rexml/parsers/baseparser`**

You are on the wrong Ruby. Ruby 3.4 dropped `rexml` from the default gems, and
the old kramdown in this dependency tree can't load it. The giveaway is the gem
path in the traceback — if it reads `/opt/homebrew/lib/ruby/gems/4.0.0/`, that's
Homebrew's Ruby, not rbenv's. Fix Prerequisites step 2, then delete and
regenerate `Gemfile.lock` (see below) — the failed run will have rewritten it
with incompatible pins.

**`Could not find github-pages-87, jekyll-3.1.6, ... (Bundler::GemNotFound)`**
**or `Unable to satisfy the following requirements: bundler (= 4.x)`**

Your `Gemfile.lock` was generated by a different Ruby. It is gitignored, so it
is safe to delete and regenerate:

```bash
rm Gemfile.lock
bundle install
```

**`undefined method 'request' for nil:NilClass` during `bundle install`**

Bundler 4.x is installed in the Ruby 3.1.4 gemset. `bundle` always picks the
newest installed Bundler, but 4.x requires Ruby >= 3.2, so it fails before it
can do anything. Remove it from this gemset — it can't run here anyway:

```bash
gem uninstall bundler -v 4.0.20   # substitute whatever 4.x `gem list bundler` shows
bundle -v                         # should now report 2.3.x
```

If any of the above still fails, you are probably not on Ruby 3.1.4 — recheck
Prerequisites step 2.

**Dependency issues generally**

```bash
rbenv local 3.1.4
gem install bundler -v '~> 2.3'
rm Gemfile.lock
bundle install
```

**`cannot load such file -- webrick`**

`webrick` is already declared in the `Gemfile`, so this normally means
`bundle install` did not complete. Re-run it. Don't run `bundle add webrick` —
that edits the `Gemfile` to add a dependency that is already there.

**Build warning: `Layout 'nofooter' requested in browse/index.html does not exist`**

Fixed — `_layouts/nofooter.html` now exists, and the build is warning-free. If
this reappears, it is not harmless: Jekyll does not fall back to the default
layout, it renders the page with *no* layout at all. That is why
`https://datarepublican.com/browse/` shipped for years with no `<head>`, no
`<title>`, no nav and no SEO tags.
