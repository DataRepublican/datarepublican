---
layout: markdown
title: How Show Don't Tell works
description: What the diagram is, what you type, and how to share it without hitting CORS.
permalink: /sankeybuilder/help/
---

# How Show Don't Tell works

{% include sankeybuilder-docs-nav.html %}

[Charity explorer](/browse/) draws money from IRS Form 990 filings. This page is the other direction: **you** type the story (or extract it from a post), and the Sankey is a picture of that file. It is user-authored. It is not IRS data.

## What you put in

- **Organizations, people, and government bodies.** An EIN is optional. Without one, the tool makes a slug from the name (`Open Society Foundations` → `open-society-foundations`) and colors the node from that id.
- **Grants** are dollar flows. Thickness follows the amount. Hover a node or a flow for name, EIN, and dollars; click a flow to edit it.
- **Partners** are relationships that are not money (board overlap, “advises”, “national partner”). They draw **dashed** and thin on purpose. A dotted line is a partner, not a grant with an unknown dollar amount. Switch the kind to Grant in the editor or the **Table** view to attach dollars.
- **Table** is a sortable spreadsheet of every organization and every flow, including nodes that are hidden on the diagram (starting set). Edit cells in place. **Add row** appends an empty organization or flow. **Show all** unhides the money nodes Grok left off the starting set.
- **Government funds** (Gov $ in the table, or the inspector field) become a grant from an implied U.S. government node. The first amount creates that `us-gov` node if the graph does not already have one.
- **Starting set** (on by default): when someone loads your file, those nodes are the ones on screen. Mark only the people and orgs the story is actually about.
- **Click modes** match the charity explorer: **Expand** (default) reveals neighbors, **Focus** isolates a node and its ties, **Zoom** frames it, **Hide** removes it (Shift-click from any mode), **Inspect** opens the editor card for a node or grant even if the editor is hidden. Zoom in/out/fit and expand/compact flows sit on the canvas, top-left. **Show circular / Hide circular** drops looping flows from the drawing. **Show Editor / Hide Editor** (green) hides the side panel so the graph can use the full width. **Show Controls / Hide Controls** (green) hides that canvas overlay for a clean screenshot; Shift / Alt / ⌘ still change click mode while it is hidden.
- **Inspector checkboxes** pick which outbound links appear. Grok is always on. ProPublica, this site’s charity pages, and federal grant search need an EIN.

A person is a 32px disc on the flow bar — a photo URL if you have one, otherwise a generic head. The bar is still the money; the face does not stretch with it.

## Three ways the file moves

1. **This browser.** Edits write to IndexedDB on your machine. Clearing site data clears the graph.
2. **A JSON file or a paste.** Save JSON / Load file, or **Paste JSON** for the blob Grok returns (markdown fences are stripped). **Save diagram** downloads the current Sankey as SVG.
3. **A URL someone else can open.** A GitHub gist (raw) is the one that scales — **Load URL** pastes that. **Share URL** copies a `#d=` fragment for tiny graphs. News sites and X do not load as data, because the browser is not allowed to fetch them.

Step-by-step for gists is on [Save and share](/sankeybuilder/share/). Pulling numbers out of a thread: paste the post URL and click **Extract from Post**. That opens Grok with a prompt that reads [the schema gist](https://gist.github.com/twinforces/706b11ec77740c11a1f258fc9d5030db) and then the post. Paste Grok’s JSON back with **Paste JSON**. The same prompt is on [Extract a post](/sankeybuilder/extract/).

## What this is not

A fraud determination, a Form 990 extract, or a substitute for clicking through to ProPublica and the 990 itself. An EIN, when you have one, is a link into those records. A missing EIN means those links stay off.
