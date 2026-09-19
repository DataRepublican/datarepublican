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

- **Icon button in the control cluster**, `aria-expanded` + `aria-controls`.
- The field opens **beside** the cluster on desktop, **across the top** on a
  phone. Derive its offset from the button size so it tracks:
  `left: calc(12px + var(--dr-tap-sm) + 8px)`.
- **Focus the input on open.** Opening a search field and not landing in it is
  the entire cost of having hidden it.
- **Escape closes and clears**, and must `stopPropagation()` — the explorer
  listens for Escape on `document` to close its detail drawer, and dismissing a
  search should not also dismiss what you were reading.
- `[hidden]` needs saying explicitly in CSS when the element also has a
  `display` rule, or `display` wins over the UA's hidden.

A page-level search and a canvas-level search are different searches. If a tool
has both, one of them is wrong.

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
- [ ] No control for a state the selection already manages.
- [ ] State setters are idempotent (`setX(bool)`), not toggles.
- [ ] Search opens from the toolbar, focuses on open, Escape clears + stops propagation.
- [ ] One measured band, observed by id.
- [ ] Display options separate from filters; out of the badge and the URL.
- [ ] Cross-module state goes through an API; no data scraped from the DOM.
- [ ] `title` on every toolbar control; a sentence for anything modal.
- [ ] Label swaps target a `.glabel`, never `textContent`.
