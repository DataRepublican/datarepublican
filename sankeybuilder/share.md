---
layout: markdown
title: Save and share a Show Don't Tell graph
description: How to put the JSON in a GitHub gist so other people can open the diagram without hitting CORS.
permalink: /sankeybuilder/share/
---

# Save and share a Show Don't Tell graph

{% include sankeybuilder-docs-nav.html %}

Other people need the **JSON**, not a screenshot. The diagram is drawn in their browser from that file. A gist is the reliable way to hand them a URL. A downloaded file is the reliable way to keep a copy. A `#d=` link is only for graphs small enough to fit in the address bar.

The builder will not fetch a news article or an X post. Those hosts block the browser (CORS). `gist.githubusercontent.com` does not.

## 1. Save the JSON from the tool

On [Show Don't Tell](/sankeybuilder/), click **Save JSON**. You get a `.json` file named after the graph title. Open it if you want to look; it is ordinary text.

## 2. Put that file in a GitHub gist

You need a GitHub account. Secret gists are fine — they are unlisted, not private. Anyone with the link can open them.

1. Go to [gist.github.com](https://gist.github.com).
2. Filename: end it in `.json` (for example `osf-alliance.json`). The name is what GitHub shows; the tool does not care.
3. Paste the file contents into the gist body.
4. Create a **secret** gist unless you want it on your public gist list.
5. On the gist page, click **Raw**. The address bar should now say `gist.githubusercontent.com`, not `gist.github.com`.

That raw URL is the one the tool can load. A typical shape:

`https://gist.githubusercontent.com/yourname/abc123def456/raw`

or, with the filename still on the path:

`https://gist.githubusercontent.com/yourname/abc123def456/raw/osf-alliance.json`

Prefer a URL **without** a 40-character commit hash in the middle. The short `/raw` form follows later edits. A URL that includes the hash is frozen on that version.

## 3. Load it in the tool

On [Show Don't Tell](/sankeybuilder/) click **Load URL**, paste the raw URL (or the gist *page* URL `https://gist.github.com/yourname/abc123def456` — the tool rewrites that to raw).

You can also send someone a link that opens the graph for them:

`https://datarepublican.com/sankeybuilder/?url=` + the raw gist URL (URL-encoded).

Example, once you have a real gist:

`https://datarepublican.com/sankeybuilder/?url=https%3A%2F%2Fgist.githubusercontent.com%2Fyourname%2Fabc123def456%2Fraw`

## 4. Keep a file copy anyway

Gists can be edited or deleted. **Save JSON** is the copy that lives on your disk. If you change the graph later, save again and paste over the gist (gist page → Edit → replace the file → Update).

## When a gist is the wrong tool

**Tiny graphs.** **Share URL** writes the JSON into the page’s `#d=` fragment and copies that address. The button reads **Copied to clipboard**. Nothing is uploaded. Chrome will refuse a fragment that is too large (tens of kilobytes). If the tool says the graph is too large for a URL, use a gist.

**Photos on person nodes.** Point `photo` at a URL the browser is allowed to fetch — a raw gist image works, a random news CDN often does not. If the image fails, the disc falls back to a generic head.

**Do not** paste the JSON into an X post and expect the tool to read it from that URL. Save a gist; link the gist.

## This site does not publish gists

There is no GitHub sign-in here. To share a graph: **Save JSON**, paste that file into [gist.github.com](https://gist.github.com), then **Load URL** with the raw link (or send someone `?url=` plus that raw URL). **Save diagram** downloads the picture as SVG, the same idea as Download SVG on the charity explorer.
