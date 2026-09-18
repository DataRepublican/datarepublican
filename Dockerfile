# The production and preview image. Nothing local needs Docker — `yarn start`
# is still the way to run the site on your machine. This exists so Coolify
# builds the site from source instead of serving a build artifact committed to
# the repo, and so previews and production are built the same way.
#
# Two stages: a Ruby+Node builder that runs the same `npm run build` used in CI,
# and an nginx image that carries only `_site`. The toolchain does not ship.

# syntax=docker/dockerfile:1

# ---------------------------------------------------------------- build ----
FROM ruby:3.1.4-slim AS build

# Ruby is pinned to 3.1.4 by .ruby-version, and it has to be: the github-pages
# gem chain expects 3.1.x and will not install on newer.
#
# Node is needed because Jekyll does not run PostCSS — the Tailwind stylesheet
# is built separately (see `npm run build:css`), and `npm run data:split`
# generates the two NoBlogs payloads that /noblogs fetches at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential git curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g yarn \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies before source, so the expensive layers survive content changes.
# `bundle install` is the slow one — a Gemfile edit is rare, a content edit is
# not, and this is the difference between a two minute deploy and a ten
# minute one.
#
# Bundler is pinned: a bare `gem install bundler` installs 4.x, which requires
# Ruby >= 3.2 and cannot run here. Gemfile.lock lists only arm64-darwin, so
# bundler resolves Linux platforms at install time — the same thing CI does.
COPY Gemfile Gemfile.lock ./
RUN gem install bundler -v '~> 2.3' \
 && bundle install --jobs 4 --retry 3

COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile

COPY . .

# data:split -> build:css -> jekyll build --destination _site.
# JEKYLL_ENV=production is what makes `url` the live domain rather than
# localhost, which the SEO tags and og:url depend on.
RUN npm run build

# Fail the build rather than ship an empty site. A Jekyll build can exit 0
# having produced very little, and nginx would serve that happily.
RUN test -f _site/index.html \
 && test -d _site/noblogs \
 && echo "built $(find _site -type f | wc -l) files"

# ---------------------------------------------------------------- serve ----
FROM nginx:alpine

# Only the output. No Ruby, no node_modules, no repo history.
COPY --from=build /app/_site /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
