---
layout: markdown
title: Extract a post into Show Don't Tell JSON
description: Paste this prompt into Grok with a thread or article. It replies with JSON the Sankey can load.
permalink: /sankeybuilder/extract/
---

# Extract a post into Show Don't Tell JSON

{% include sankeybuilder-docs-nav.html %}

On [Show Don't Tell](/sankeybuilder/) paste a post URL and click
**Extract from Post**. That opens Grok with the prompt below plus the URL.
Grok reads the schema from
[this gist](https://gist.github.com/twinforces/706b11ec77740c11a1f258fc9d5030db)
and replies with one JSON object. Paste that JSON with **Paste JSON**
(fences are fine), or **Load file**. To hand someone a URL, follow
[Save and share](/sankeybuilder/share/) and put that JSON in a gist.

The graph is **your** reading of a source. It is not IRS data. Do not invent
EINs.

<pre id="extract-prompt" class="max-w-column overflow-x-auto whitespace-pre-wrap rounded-card border border-rule bg-card p-4 text-dense">Loading prompt…</pre>

<p><button type="button" id="copy-extract" class="dr-btn">Copy prompt</button>
<span id="copy-status" class="text-meta" hidden>Copied.</span></p>

The full schema also lives in the repo as
[`extract-prompt.txt`](extract-prompt.txt) if you want to read it without
opening GitHub. Edits go on the gist; that file is a snapshot.

<script type="module">
  import { extractBootstrapPrompt } from "/sankeybuilder/models.js";
  const t = extractBootstrapPrompt();
  const pre = document.getElementById("extract-prompt");
  const btn = document.getElementById("copy-extract");
  const status = document.getElementById("copy-status");
  pre.textContent = t;
  btn.addEventListener("click", async () => {
    await navigator.clipboard.writeText(t);
    status.hidden = false;
  });
</script>
