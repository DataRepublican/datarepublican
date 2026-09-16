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

## Run the site

1. `yarn start`
2. Open the site at `http://localhost:4000`

This runs the CSS watcher and the Jekyll dev server together.

> **Before you commit, run `git restore docs/`.**
>
> `docs/` is the committed build output that GitHub Pages serves today, and the
> dev server rewrites it in place — a `serve` run repoints canonical links,
> `og:url` and `og:image` across ~20 pages at `http://localhost:4000`.
>
> This warning goes away once `docs/` stops being committed. That is the second
> half of the CI change; see **Deploying** below.

If you only want one piece:

- `bundle exec jekyll serve --livereload` — the server on its own (add
  `--verbose` for more output)
- `yarn run watch:css` — the Tailwind watcher, only needed when editing CSS

## Build the site

```bash
npm run build
```

That is PostCSS then Jekyll, in that order, with `JEKYLL_ENV=production` set.
Both halves matter:

- Jekyll does **not** invoke PostCSS, so `assets/css/styles.css` has to be
  generated before the site build or you ship the previous stylesheet.
- `JEKYLL_ENV=production` has to be an environment variable. Passed *after* the
  command, Jekyll reads it as a positional argument and silently ignores it,
  which is what the old `doIt.sh` did.

Output goes to `_site/`, which is gitignored. Serve it with
`npm run serve:build` (stop the dev server first — same port).

## Deploying

CI builds and publishes. `.github/workflows/deploy.yml` runs on `master`, builds
the site and pushes it to GitHub Pages, with two gates before anything uploads:

- **Size.** The build is ~430 MB against a 1 GB Pages ceiling, so it fails with
  a message naming the cause rather than at upload time with an opaque one.
- **The route contract.** `tests/routes.txt` lists every published URL. A build
  whose routes differ from that file never reaches production. Removing a page
  deliberately means editing that file in the same commit, so it shows up in
  review.

`.github/workflows/ci.yml` runs the same build plus the test suite on every PR.

### Finishing the cutover

Pages **Source** is already set to *GitHub Actions*. One step remains:

1. Verify a deploy serves the live site correctly.
2. Then remove `docs/` from git and delete the `git restore docs/` warning above.

Until step 2, `docs/` is dead weight — committed, 632 MB, and not what is being
served.

> Checking the live site by HTTP status will not work: `datarepublican.com`
> returns **200 for any path**, including ones that do not exist. Compare
> content, not status codes.

## Testing

```bash
npm run build
npm run serve:build &          # or: python3 -m http.server 4000 --directory _site
npm test                       # Playwright
npm run test:routes            # every URL in tests/routes.txt still resolves
```

Serve the build with a plain static server. `npx serve` is **not** equivalent:
it rewrites `/officers/index.html` to `/officers`, dropping the trailing slash,
so relative script tags resolve against `/` and the page 404s its own
dependencies. GitHub Pages keeps the trailing slash.

The suite covers the usual page-loads-and-has-a-title checks, plus:

- **Mobile reachability** (`test_dsa_explorer_mobile`, `test_noblogs_mobile`) —
  controls present, ≥44px, and *not occluded* at 390px. A tool can load fine and
  return correct data while being unusable with a thumb; these catch that.
- **The tools index** (`test_tools_index`) — every entry in `_data/tools.yml`
  resolves, and each sort actually reorders. Read by *visual* order, since the
  sorting is CSS `order` and DOM order would pass regardless.
- **Payload regressions** — that no `*.embed.js` logo blob is loaded, and that
  `quotes.embed.js` is fetched once rather than twice.

Use real clicks in new specs, not dispatched `MouseEvent`s. A synthetic event
goes straight to its target and cannot be intercepted, so it will pass happily
while an invisible overlay eats every tap a real thumb makes.

## How the site is put together

- **Chrome** — `_layouts/default.html` is banner → masthead → nav → content →
  footer. One DOM order for both layouts; the nav pill is `fixed` at the bottom
  on a phone and `static` under the wordmark at `md`. `_data/banner.yml` drives
  the site-wide band; `enabled: false` removes it everywhere.
- **The tools index** — `/` is the tools page, which is why the nav has no Home
  item. `_data/tools.yml` is the single source of truth for all thirteen tools.
  `updated` is the last commit touching that tool's directory, so the default
  "Latest" sort means something; keep it honest.
- **Compact chrome** — tool pages get a one-line masthead and a shorter banner
  by default; the five narrative pages opt out in `_config.yml`.
- **Bottom sheets** — `assets/js/sheet.js`. On a phone, a tool's detail panel
  becomes a sheet over the canvas instead of a column 700px below the fold.
  At ≥768px it is `display: contents` and the panel is an ordinary side column.
  Its styles live *outside* `@layer components` in `assets/css/main.css`,
  because Tailwind purges layer CSS whose classes never appear in any HTML —
  and every class there is created at runtime.

## Data and generated assets

The heavy datasets are built by a separate pipeline and dropped into this repo.
Their on-disk shape and URL contract are an interface — do not change how a tool
fetches its data without checking the tool still works.

Two generated things do live here, both idempotent and safe to re-run:

```bash
node scripts/extract-logo-blobs.mjs   # after new *.embed.js logo blobs land
node scripts/capture-previews.mjs     # home page card images
```

`extract-logo-blobs.mjs` turns `dsa-explorer/logos/*.embed.js` and
`noblogs/graph/logos.embed.js` — base64 PNG loaded as blocking scripts — into
image files plus a small manifest. Base64 does not compress, so those were 21 MB
and 12.6 MB *on the wire*. The `.embed.js` files stay in the repo as the
pipeline's artifacts and are excluded from the build in `_config.yml`.

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
