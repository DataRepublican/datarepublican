# Tool chrome — the pattern

How a full-viewport tool arranges the controls around its canvas. Settled on
`noblogs` in September 2026 and drawn on the Paper boards
`trumpblogs 3/mobile` and `trumpblogs 3/desktop` (page `p-2-0`).

`dsa-explorer` and every tool built after this follows it. The adoption rule
still applies — migrate what you touched — but **a new tool has no excuse.**

---

## 1. One row per question, ordered by how often it is asked

A tool's chrome answers three questions, and each gets exactly one row:

| Row | Question | Holds |
|---|---|---|
| 1 | *What am I looking at?* | tool title, the live count, the legal link |
| 2 | *Which view?* | the view toggle |
| 3 | *Which subset?* | Filters, then search |

**Phone: three stacked rows, in that order.** Views above search, because you
switch view far more often than you type a query, and a thumb reaches the top
of the stack last.

**md and up: rows 2 and 3 become one row** — subset controls left, views right.
You narrow the data on the left and choose how to draw it on the right. That is
the conventional reading and it is what the boards settle.

Write the markup in the PHONE's order and use `order` to swap at md. The phone
is the layout that cannot absorb a compromise; desktop has room to be rearranged.

```css
.nb-toolbar{display:flex;flex-direction:column;gap:8px}
@media(min-width:768px){
  .nb-toolbar{flex-direction:row;align-items:center;justify-content:space-between}
  .nb-toolbar .tabs       {order:2;flex:none}
  .nb-toolbar .nb-controls{order:1;flex:0 1 auto}
}
```

### The header is a flex COLUMN, never flex-wrap

`noblogs` was one `flex-wrap` row holding five things. On a phone it wrapped
into five bands and the map started below the fold — and because the row count
was a function of viewport width *and* content length, the height had to be
measured at runtime and kept surprising us.

A fixed column of three rows has a predictable height. You still measure it
(see §6), but you are measuring one number that rarely changes rather than
tracking a reflow.

---

## 2. Nothing permanent sits on the canvas

The canvas is the product. Anything drawn on top of it is rent, and it has to
earn the space every time the tool is opened.

**Delete an overlay that duplicates a control you already have elsewhere.**
noblogs' `.info` card held a category legend that was a *second* category
filter, ANDed with the facet one — two controls for one question, and the
facet version already had counts and swatches. The card went; nothing was lost.

When you remove an overlay, every piece of it gets a home, and each move should
be a de-duplication rather than a relocation:

| Was | Went to |
|---|---|
| counts | the header's live status line (`#subcount`) — already announced to a screen reader |
| a display toggle | a group in the filter popover, behind a real API (§7) |
| a colour legend | the facet group that already lists the same categories |

If something has no home, that is a signal the thing itself was not carrying
its weight.

**Check what the DESTINATION was already saying.** Redistribution is where you
overwrite, not where you drop, and the overwrite is silent. The status line had
been answering *how much of the corpus matched* — "107 of 7,673 blogs match" —
and when the map card was deleted, the pin count moved into that same line and
took it over: "34 of 107 mapped". Nothing was lost from the card; the
destination's own job was. It reads as a plausible sentence, the numbers are
all real, and it looks for all the world like a data regression to anyone
comparing against production.

So after every move, read the destination out loud in each state it can be in
— filtered and not, per view — and check it still answers what it answered
before. A fraction whose halves are equal ("7,673 of 7,673") is the other tell
that a line is being written by two features that have not been introduced.

### Corners belong to the vendor

Leaflet puts its zoom control at **top-left**. Cytoscape's fit/zoom conventions
are the same corner. An overlay pinned there covers the one control every user
reaches for first. noblogs' card did exactly that, at every width.

Before you pin anything to a canvas corner, open the tool and look at what the
vendor already drew there.

A **transient** popover may overlap a vendor control — you opened it, it closes
on scrim tap, and you are not zooming while you filter. **Permanent** chrome may
not.

---

## 3. Legal text is a modal, not a band

The disclaimer was a full-width amber callout pinned under the header. Its
resting state was the word "Disclaimer" and a triangle — a permanent row of a
390px screen, on every view, for a notice that is read once if ever.

It is now a `.dr-dialog-open` link in the identity row that opens a
`.dr-dialog`. The text is unchanged and still one keystroke away.

**Use a native `<dialog>` with `showModal()`.** Not `show()`, and not a
hand-rolled overlay. See `assets/css/components/dialog.css` for the full list of
what the platform hands over, but the one that matters most here:

> **The top layer.** A modal dialog renders above every stacking context
> regardless of z-index. Leaflet numbers its panes to 1000 and the repo's rule
> is that nothing it authors goes above 100 — the top layer is how a modal
> clears a vendored z-index without joining the bidding war.

`.dr-dialog` is **not** a replacement for `DRSheet` and must not become one. The
sheet is a persistent, draggable, detented *view of a selection* that coexists
with the canvas. A dialog is a modal interruption you dismiss. The phone styling
makes the dialog look like a sheet because bottom-anchored is right for a thumb,
not because they are interchangeable.

---

## 3a. One bottom-sheet motion, and every sliding surface uses it

**There is exactly one "arrives from an edge" motion on this site:**

```css
transition: transform var(--dr-dur-sheet) var(--dr-ease-sheet);   /* 240ms, cubic-bezier(.32,.72,0,1) */
```

`.dr-sheet` and `.dr-dialog` are both instances of it, and so is anything added
later. **This is the rule that was broken first.** `.dr-dialog` shipped with no
transition at all, so the disclaimer appeared instantly while the detail sheet
eight pixels away slid — two bottom-anchored surfaces, two different physics,
one of them obviously wrong. If you are writing a new surface and reaching for
a duration, you are already off the path: take the tokens.

On a phone the motion is a **pure slide**, no fade. A fade-and-lift is the
desktop gesture for a centred card; using it on something pinned to the bottom
edge is the same divergence one step smaller, which is why `.dr-dialog`'s
mobile block explicitly re-states `opacity: 1`.

### Animating a `<dialog>` — the part that silently half-works

```css
transition: transform var(--dr-dur-sheet) var(--dr-ease-sheet),
            overlay   var(--dr-dur-sheet) allow-discrete,
            display   var(--dr-dur-sheet) allow-discrete;
```

`allow-discrete` on `display` and `overlay` is not optional. A modal dialog
leaves the top layer the instant `close()` is called, so without it **the open
direction animates and the close direction does not** — and you will test the
open direction, see it work, and ship. `@starting-style` supplies the
from-state, because on open the element has no previous computed style to
animate from.

`getComputedStyle` cannot verify the closed state: a closed `<dialog>` is
`display: none` and its transform resolves to `none` whatever the rule says.
Assert the motion by sampling the element's position mid-flight instead.

## 3b. The sheet and its consumer have to agree

`.dr-sheet` wraps a panel the tool already owns, so there are two elements that
can disagree. Three ways they did:

- **Ground.** The sheet was hardcoded `#fff`; noblogs' `#panel` sits on the
  page ground by design. Stacked, that painted a white band above the content
  and another below it, which read as a header and a footer the sheet does not
  have. The sheet exposes `--dr-sheet-surface` and the consumer overrides it —
  never restyle `.dr-sheet` itself.
- **Close buttons.** `DRSheet` adds one; most panels already have their own.
  On a phone they stacked into two X's in two header bars. **The sheet's wins**
  (it is the one that also dismisses the sheet); hide the tool's own below md.
- **Room at the top.** `.dr-sheet__close` is a 44px target pinned to the
  top-right. The grip is the sheet's header row and **must be at least as tall**,
  or the close overhangs whatever the panel renders first and every consumer
  has to leave a hole in its own corner. Reserved once, in the component.

The general rule: when a shared wrapper and its consumer both have an opinion
about a surface, the wrapper exposes a variable and the consumer sets it. Two
stylesheets independently deciding what colour something is will drift.

## 4. A control for a state that manages itself is not a control

The graph had a `‹` / `›` chevron floating over the canvas to collapse the
detail panel. But the panel is empty until you click a node and empties again
when you click the background — so the button's only honest use was hiding a
panel that already had something in it, and the same background click did that
*plus* the deselect you actually wanted.

Before adding a control, ask what state it manages and whether anything else
already manages it. If the answer is "the selection does", delete it.

### Express state with a setter, never a toggle-by-side-effect

Three call sites in the graph reached for `panelToggle.onclick()` — a **toggle**
— to mean "close" or "open" *specifically*. Each had to test the current state
first and skip the call if it was already right. Miss that guard and the call
does the exact opposite of what the call site wanted.

```js
// Wrong: every caller must know the current state to use it safely.
function togglePanel(){ el.classList.toggle('collapsed'); }
if (!el.classList.contains('collapsed')) togglePanel();   // "close"

// Right: idempotent, and the call site says what it means.
function setPanel(open){
  if (el.classList.contains('collapsed') === !open) return;
  el.classList.toggle('collapsed', !open);
  requestAnimationFrame(() => cy.resize());
}
setPanel(false);
```

---

## 5. Search is a control, not furniture

A search field parked on the canvas is a white box permanently covering data.
The graph's sat top-centre over the densest part of the network **and**
duplicated the explorer's page-level field two rows above it.

Search opens from the toolbar:

The header field is the only field. noblogs' graph went through three canvas
searches — a 270px box parked top-centre, one hidden behind a toolbar button,
one growing out of that button — before the answer turned out to be that a
canvas does not need one. If you are positioning a search over a visualization,
stop and ask what the header field is for.

**If a control cluster must hold an expanding field anyway** (a toolbar with no
header above it), two things: it expands out of its own button rather than
appearing beside it, and in a flex **column** the expanded part must not sit in
flow — the column's width is its widest child and `align-items: stretch` hands
that width to every sibling, so the field drags all the buttons wider with it.
- **Escape closes and clears**, and must `stopPropagation()` — the explorer
  listens for Escape on `document` to close its detail drawer, and dismissing a
  search should not also dismiss what you were reading.
- `[hidden]` needs saying explicitly in CSS when the element also has a
  `display` rule, or `display` wins over the UA's hidden.

A page-level search and a canvas-level search are different searches. If a tool
has both, one of them is wrong.

### On a network view, search FINDS. It does not filter.

One search field, in the header, and **what it does is the view's job, not the
field's**:

| view | the query | |
|---|---|---|
| map, list | **narrows** — feeds `filtered()` | the set is the point |
| graph | **finds** — highlights, frames, never removes | the *structure* is the point |

Filtering a network deletes the thing you opened it to look at. It is also
arithmetically hopeless: noblogs' graph holds **217 of 7,673** blogs, so a
corpus query lands in it by luck —

```
antifa     1,245 corpus →  108 nodes      berlin   349 →  7
anarchist  2,231       →   71             squat    758 →  9
adl            3       →    1             amnesty    9 →  1
```

— and the most natural query of all, naming an institution, **cannot work at
any scale**: the 77 institutions are nodes on the canvas, not rows in the blog
index. No filtering search will ever return one.

So `F.q` is view-dependent while the **facets are not**. The facets still
cross-filter every view (that contract is untouched); only the text query
changes meaning. Keep the two filter functions separate and named for it —
`filtered()` is facets AND query, `facetFiltered()` is facets alone.

Three things follow, and each one is a bug if you miss it:

- **Facet counts** must be scoped the same way the view is. Counting with the
  query applied, on a view where the query does not filter, makes the panel
  disagree with the canvas.
- **The status line** counts what the view can show — nodes here, not corpus
  rows. "1 of 7,673" describes a set the graph cannot display.
- **Switching views must re-render.** The line and the facet groups are both
  view-dependent now, so a switch that only toggles `display` leaves the
  previous view's numbers on screen.

Frame what you found: centre a single hit, fit several, and **leave the camera
alone on zero** — moving the view to show an empty result is worse than not
moving it. A miss says so in the status line; it does not empty the canvas.

---

## 6. Measure one thing, and only what still moves

Canvases size against what is left of the viewport:

```css
height: calc(100dvh - var(--nb-header-h,56px) - var(--nav-clearance));
```

Every literal in that expression is a bug waiting for a different screen, so
the header height is measured. Two things used to make this harder than it is,
and the pattern removes both:

- a **separate filter bar** below the header — a second measured band. Filters
  is a control *inside* the header's controls row, so there is one band.
- a **disclaimer that changed the header's height when it opened** — the modal
  does not touch layout at all.

What is left is one `ResizeObserver` on one element. **Measure by id**
(`#nb-header`): the site masthead is also a `<header>` and comes first in the
DOM, so `querySelector('header')` returns the wrong element — a bug this repo
has already shipped twice.

---

## 7. Display options are not filters

A checkbox that changes *what is drawn over* the data is not a checkbox that
changes *which data exists*. Keep them apart:

| | Filter | Display option |
|---|---|---|
| state | the `F` set | its own variable |
| URL | yes | no |
| resets paging | yes | no |
| counts toward the Filters badge | **yes** | **no** |

A badge reading "1" when the only thing set is "edges are visible" is lying
about the result count.

Group display options under their own `<legend>` in the popover (`Map`), and
render the group **only on the view it applies to**.

### The panel's reset

`Clear all filters` is the panel's reset, so it sits at the **trailing edge**,
sentence case, and is **`disabled` when there is nothing to clear**. On the
leading edge it read as the first item of the first filter group; at full
strength with an empty set it was a control advertising work it cannot do.

Use `disabled`, not a faded class — the fade is the visible half of a state the
keyboard and the screen reader should also get.

### `hidden` and `display`, for the second time

A count badge that a tool toggles with `hidden` needs
`.dr-btn__count:not([hidden])` on its `display` rule. `hidden` only sets
`display: none` through the UA stylesheet, so a bare `display: inline-flex`
beats it and the badge shows "0" forever. **This repo has now paid for this
trap twice** — `.dr-sheet__scrim` carries the same note. Any rule that sets
`display` on an element something toggles with `hidden` has to say `:not([hidden])`.

### Reach into a module through an API, not its DOM

The co-citation toggle used to live in the card and `map.js` read
`edgeToggle.checked` live. Moving the checkbox into the filter popover would
have broken it silently — that popover rewrites its own `innerHTML` on every
facet change, so any element inside it is destroyed and recreated with no
listener attached.

The module owns the boolean and exposes `setEdges(on)`. The standalone page
still ships its own `#edgeToggle` and writes through the same variable.

**Corollary: never read data out of the DOM.** `CATCOLOR` was scraped from the
legend's inline swatch styles, on the argument that a second copy would be a
second thing to keep in step. Right about the risk, wrong about the direction:
it made a node that exists for *humans* into a data dependency, so deleting the
legend — the correct design change — would have blanked every facet swatch
instead of failing loudly. State it once in JS, next to a comment naming the
real authority (`map_data.js`).

---

## 8. Tooltips name what a mode does

`title` on every toolbar control, including the ones that already have a word.

An icon can name a thing but cannot say whether a mode is on; a label can say
which mode it is but not **what it does**. "Focus mode" and "Target edges only"
are the cases that need a sentence, and a tooltip is where it goes.

Use `title`. No JS tooltip machinery: it is free, works on hover and on keyboard
focus, and is what `tests/test_toolbars.spec.js` already asserts on icon-only
controls.

### Never swap a button's label with `textContent`

```js
b.textContent = 'Rendering…';   // deletes the <svg> child, permanently
```

The graph's Export button did this and lost its icon on the first export, for
the whole session. Put the word in its own element and swap that:

```js
const lab = b.querySelector('.glabel'), was = lab.textContent;
lab.textContent = 'Rendering…'; b.setAttribute('aria-busy','true');
// …
lab.textContent = was; b.removeAttribute('aria-busy');
```

`.dr-btn[aria-busy="true"]` is already styled, and `aria-busy` is what a screen
reader reads.

---

## 9. What the tests hold

Re-point a spec when a mechanism changes; do not delete it. The property is
usually still real and only the trigger moved.

| Spec | Property |
|---|---|
| `test_toolbars.spec.js` | every `#controls` button is a `.dr-btn`, named, tooltipped; 32px desktop / 44px phone; the legend never reaches the control column |
| `test_disclaimer.spec.js` | full text reachable without a pointer; never the smallest type; **and for the modal**: `:modal` (so `show()` can't creep in), focus returns to the opener, opening does not reflow the header |
| `test_review_regressions.spec.js` | `.collapsed` really moves the grid column — now driven by selecting a node; the search field boots hidden, opens beside the controls, and takes focus |
| `test_noblogs_mobile.spec.js` | `--nb-header-h` is the tool header's height and not the masthead's |

**When you add a control to a cluster, move the legend's height budget with
it.** `graph.css` reserves `calc(100% - 340px)` for eight 32px buttons plus gaps
and the inset. That number is derived from the thing directly above it in the
same box — which is what makes it stable, and what `calc(100vh - 150px)` never
was.

---

## Checklist for the next tool

- [ ] Three rows: identity + legal / views / subset. Phone stacks, md merges 2+3.
- [ ] Header is a flex column, not `flex-wrap`.
- [ ] Canvas has no permanent overlay. Vendor corners are clear.
- [ ] Legal text is a `.dr-dialog`, opened with `showModal()`.
- [ ] Every sliding surface uses `--dr-dur-sheet` / `--dr-ease-sheet`; a
      `<dialog>` also needs `allow-discrete` + `@starting-style`.
- [ ] The sheet and its panel agree: `--dr-sheet-surface` set, the tool's own
      close hidden below md, nothing rendered under the 44px grip row.
- [ ] No control for a state the selection already manages.
- [ ] State setters are idempotent (`setX(bool)`), not toggles.
- [ ] One search field. On a network view it finds and frames; it never
      filters. Facet counts, the status line and view switches all follow.
- [ ] The panel reset is trailing-edge, sentence case, `disabled` when empty.
- [ ] Any `display` rule on a `hidden`-toggled element says `:not([hidden])`.
- [ ] One measured band, observed by id.
- [ ] Display options separate from filters; out of the badge and the URL.
- [ ] Cross-module state goes through an API; no data scraped from the DOM.
- [ ] `title` on every toolbar control; a sentence for anything modal.
- [ ] Label swaps target a `.glabel`, never `textContent`.
