# Components — current → target

Geometry and states are drawn on `system-primitives` and `system-surfaces` in
Paper. This file is the migration map: what each `.dr-*` class replaces, so a
partial migration stays legible to whoever arrives next.

**The adoption rule: migrate what you touched, and only what you touched.**

## The global `button` rule — do NOT de-specify it

`assets/css/main.css` paints every bare `<button>` slate-900 at `min-width:65px`
with a right margin at md, because ~20 older tool pages were built against it.

**`:where(button)` does not work, and this was measured.** A before/after sweep
of all 146 buttons across all 34 routes says it changes **122 of them on 23
routes**: `/ned/`'s search button, `/nonprofit/`'s filter and back-to-top and
`/expose/`'s add-EIN all go transparent, and the banner button loses its padding
on every page.

The reason: **Tailwind v3 emits no real cascade layers.** `@layer base/components/
utilities` is a build-time concept and the output is plain concatenated CSS
(`grep -c '^@layer' assets/css/styles.css` → 0). So at zero specificity the rule
stops beating *preflight's* own `button { background-color: transparent }`, which
is (0,0,1) and comes first. An earlier version of this file claimed layer order
would protect it. It does not.

**The tax was never specificity.** A class is (0,1,0) and already beats an
element selector — `.dr-btn` needs no `!important`. The tax is that the global
rule sets properties a component never thinks about (`min-width`, `margin-right`,
padding, size, weight), so each control had to zero them by hand.

So `.dr-btn` absorbs the reset once, and the global rule is left alone. Scoping
it to the legacy pages is still the right end state — `.legacy-tool button` plus
a class on ~20 files — and belongs to whoever is next in them.

**If you touch that rule, sweep first.** Capture computed `backgroundColor`,
`color`, `minWidth`, `borderRadius`, padding, `marginRight`, `fontSize` and
`fontWeight` for every button on every route in `tests/routes.txt`, change,
re-capture, diff. And take the baseline when the server is idle: two routes in
the first sweep captured *unstyled* buttons because the page loaded during a
Jekyll rebuild, which reads in the diff exactly like a regression.

## Primitives

| Class | Replaces |
|---|---|
| `.dr-btn` | four unrelated shapes: the nav/banner pill; `#nb-filterbar button`; `#controls button` in graph + dsa (6px rect, overridden to a pill below 767 anyway); `.loadmore` (~39px, fails the tap target) |
| `.dr-btn--icon` | four close/collapse controls, incl. panel toggles that signal state by swapping `‹`/`›` with no `aria-expanded` |
| `.dr-btn[aria-pressed]` | three `textContent` swaps: "Focus: on/off", "Hide/Show inferred", "Target edges only". `main.css` **already** styles `[aria-pressed="true"]` — only the attribute is missing |
| `.dr-seg` | three `<div>`s with click handlers. Not focusable, no role, no arrow keys |
| `.dr-field` | three search inputs (340 / 270 / 260px). **Two of them float over a canvas and duplicate the page-level field — delete those**; it also frees the canvas top edge where dsa's mobile controls collided |
| `.dr-chip` | six chip and legend-row patterns across three files, 19–25px tall, all `<span>` + onclick |
| `.dr-tag` | four tag/badge patterns at radius 4/6/12. **Never carries an inline background** — dsa's data colouring becomes `--tag-bg` on a `solid` tone |
| `.dr-check` | `.fitem`, which set `pointer-events:none` on the real checkbox and handled the click on the row. Fixed natively in noblogs: `<label>` around `<input>` inside `<fieldset><legend>`, handler on the input's `change`. **When a list rebuilds itself, restore focus** — see below |
| `.dr-link` | five source-link classes, all `#1155CC`. Promote dsa's `fmtUrl()` to a shared helper |

Button sizes: `md` = 44px at every width. `sm` = 32px, **desktop-only**, inside a
panel or toolbar. Never `sm` below md.

**Overlay stacks in the same corner share a height budget.** The graph and DSA
both pin controls top-left and the legend bottom-left, so the legend needs a
`max-height` that reserves the control column. That number is legitimate where
`calc(100vh - 150px)` was not: it is derived from the thing directly above it in
the same box, not from a guess at unrelated page chrome. Watch the ordering —
a media query adds no specificity, so an override written above the rule it
means to beat loses on source order.

## Surfaces

| Class | Replaces / decision |
|---|---|
| `.dr-card` | drops the `translateY(-2px)` hover (it makes an auto-fill grid shimmer). Its type now clears the floors — every line of it was 10–11.5px, which made the library view's main content the smallest text in the tool. **Still a `<div>` with onclick**: not keyboard-reachable, not openable in a new tab, no `href` to copy. Deliberately parked, not overlooked — becoming an `<a>` is the fix when someone is next in that file |
| `.dr-tile` | KPI values lose their six colours. Two of the six were already identical because `--gold` and `--med` are the same hex |
| `.dr-panel` | three layouts. **Docked column wins** over noblogs' fixed overlay: an overlay + scrim dims the map you just clicked, the failure the sheet exists to fix. `clamp(320px, 30vw, 392px)` absorbs 340/370/392 and deletes the stray `@media(max-width:820px)` with its 768–820 dead zone |
| `.dr-sheet` | keep as-is structurally. Gains a visible title and keyboard detent control |
| `.dr-popover` | the hand-rolled facet sheet + `#nb-facetscrim` + `place()` |
| `.dr-legend` | three legends, **all three now converted.** dsa's bar + expandable key won the design and was, for a while, the only one still built from `<div>`/`<span>` with a delegated click. Rows are `<button aria-pressed>`, the collapse is a `<button aria-expanded aria-controls>`, everything 44px on a phone. Swatch *shape* stays a variable so the map keeps circles and the graph keeps squares. Bound a floating key by its own container, never `calc(100vh - …)`. See the polarity note below |
| `.dr-controls` | two near-identical toolbars, both converted: icon-first `.dr-btn` controls, Lucide glyphs, `.dr-btn--icon` where the action has a conventional icon and no state. **`sm` (32px) applies above md inside a toolbar** — seven stacked 44px buttons make a column taller than the room above the legend, so the thumb floor is a floor for thumbs. The unused `.dr-controls` block in `main.css` is still there and still unadopted; its `!important`s were never needed |
| `.dr-callout` | three amber disclaimers at 10 / 10.5 / 11px with different line-heights. **Goes up to 13px**, and becomes a real `<details>` with a 44px summary on phones. **Superseded for legal text** — see `.dr-dialog` below. Still correct for an in-flow notice you want read without a click |
| `.dr-dialog` | the legal callout, where it was a permanent full-width band. A native `<dialog>` + `showModal()`, opened by a `.dr-dialog-open` link in the tool's identity row. Bottom sheet on a phone, centred card above md. **Uses the TOP LAYER, so it sets no z-index** — which is how a modal clears Leaflet's 1000 without joining the bidding war. `noblogs` is converted; `dsa-explorer` still has the `<details>`. Full rationale in `assets/css/components/dialog.css` and §3 of `tool-chrome.md` |
| `.dr-empty` | four empty states at 13px → **16px, done** (`.empty`, `.pempty`, graph `aside .empty`, dsa `#panel .empty`). Still to gain the action that resolves them |
| `.dr-loading` | `role="status"` on the two noblogs veils, **done**; they read at 16px. The error state still has no retry |

## Detail panel anatomy — `.dr-detail`

`__note` keeps noblogs' left rule and drops dsa's fill — a fill *and* a rule
*and* a half-radius is three decorations doing one job. Also `__header`, `__kv`,
`__srclist` (keep dsa's `›` prefix), `__connlist`.

### The label recipe — done, and how

**Thirteen** rules across three files did one job: 10, 10.5 and 11px, four
letter-spacings, three greys, every one of them uppercase. They are now one
grouped rule per file, all reading `--dr-text-label`, `--dr-font-ui` and
`--dr-ink-faint`:

| File | Grouped selector |
|---|---|
| `noblogs/index.html` | `.kpi .k, .sec h4, .q .qhd, .ctlab, details.news>summary` |
| `noblogs/graph/graph.css` | `.kv b, .conns h3, .quotes h3` (each under `.nbgraph aside`) |
| `dsa-explorer/index.html` | `#legend h4, #panel .kv b, #panel .conns h3` |

Two labels stay out of the group, for reasons worth keeping:

- **`.tag`** (both tools) keeps `color:#fff` — its background is set inline from
  the data, so `ink-faint` would make it unreadable. It takes the size and the
  sentence case, not the colour.
- **`details.qdrop>summary`** in the graph keeps `#B91C1C`. It flags
  target-designation quotes, so the red is a data signal, not chrome.

**This is not a class, and that is deliberate.** Putting `.dr-label` in the
markup would mean editing three files' JS template strings — the adoption rule
says migrate what you touched, and CSS was what needed touching. `.dr-label` is
still the end state for markup that is being rewritten anyway.

**The grouped rule must stay BELOW the rules it overrides.** It carries no extra
specificity — `.kpi .k` in the group is the same (0,1,1) as `.kpi .k` above it —
so source order is the entire mechanism. Moving it up a few lines silently
restores the uppercase, and a grep of the source will not catch it.
`tests/test_labels_and_status.spec.js` asserts computed `textTransform`,
`fontSize` and `letterSpacing` on every site, which does.

## Legend polarity, and why it differs in all three

Not an inconsistency. Each tool's pressed state means what its own legend means:

| Legend | Selection model | `aria-pressed="true"` means |
|---|---|---|
| noblogs map | multi-select | this category is **chosen** |
| noblogs graph | multi-select, all on at load | this class is **shown** |
| dsa-explorer | single-select **with clear** | this is the current being **isolated** |

dsa is `aria-pressed` and not a `radiogroup` on purpose: one current at a time,
but re-clicking the active one clears it, and **a radio cannot be unset**.
Clearing is the common case there.

### Polarity decides the PAINT, not just the semantics

**If everything starts pressed, pressed cannot be the loud state.** The graph's
rows all load shown, so a solid accent fill on `[aria-pressed="true"]` painted
the entire panel dark — a list of toggles reading as a list of selections, with
the state carrying no information because nothing ever lacked it.

| legend | default | pressed looks like |
|---|---|---|
| noblogs map | nothing chosen | **filled** — the exception stands out |
| dsa-explorer | nothing isolated | **filled** — one at a time |
| noblogs graph | *everything* shown | **a ticked checkbox**, row otherwise plain |

So the graph's rows carry a checkbox drawn in `::before` — the same shape as
the filter panel's category rows, which do the same job with real
`<input type="checkbox">`. Off dims the **swatch and the label**, never the
box: you still have to read what you turned off.

A box in CSS rather than a real input because the row is already a
`<button aria-pressed>`, and an input inside a button is invalid.

**Watch for blanket rules reaching legend rows.** This came from
`.nbgraph #stage button[aria-pressed="true"]`, written for the toolbar's Focus
mode and Target-edges toggles — legend rows are also buttons with
`aria-pressed`, also inside `#stage`. Scope a toolbar's pressed fill to the
toolbar (`#controls`), never to the canvas.

Two further rules the dsa conversion settled:

- **A button that does something is not a button that is in a state.** The
  country rows fly the camera to a box; they are buttons with no `aria-pressed`.
  The shape key is not interactive at all and stays a `<div>` — converting it
  would have added a focus stop that does nothing.
- **Where a control is drawn twice, both copies carry the state.** dsa's bar
  chips and its full-key rows are one control with two presentations; the
  handler already shared them, and now `setIdeoFilter` writes `aria-pressed` to
  both in the same loop that writes `.active`.

## The status line — `#subcount`

The tool's only running commentary. `render()` rewrites it on every filter
change and it said nothing to a screen reader; it is now
`role="status" aria-live="polite" aria-atomic="true"`. **`aria-atomic` matters as
much as `aria-live`** — without it the reader announces the one number that
changed, out of its sentence.

A live region forces a debounce. Undebounced it interrupts the reader on every
letter and the count is never heard whole. The same 200ms also stops every
keystroke rebuilding `#facets.innerHTML` and re-rendering the grid, the map layer
and the graph filter over ~5,000 records. 200ms sits below the ~250ms an average
typist leaves between keys, so a pause reads as "done typing".

All three search fields are debounced at 200ms — noblogs' page search, the
graph's node search and dsa's. Only the typing path: facet checkboxes, clear-all
and the URL restore are discrete events and stay immediate. dsa's camera glide
keeps its own 350ms *after* the debounce, and its `clearTimeout` fires
immediately on input so a queued glide can never land mid-word.

**Test that nothing happened yet.** A spec that only checks the count eventually
updates passes with the debounce removed.

## Accessibility debt this clears

Tabs, chips, legend rows and the clear-all control are non-focusable
`<div>`/`<span>` with onclick. Focus styling exists on exactly one selector
site-wide (`.dr-sheet:focus-visible`); `#search:focus` *removes* the outline.
Tap targets: `.loadmore`, `.fitem`, `.lgrow`, the legend `.row`s and `.chip`s in
all three tools, and `.clearf` (20px, the smallest hit area in the tool) are all
done. **32px is the mouse floor, 44px the thumb floor** — `.clearf` and toolbar
buttons take `--dr-tap-sm` above md and `--dr-tap` below it.

Not defects, so do not "fix" them: inline source links measure 15–18px tall
because they are links inside flowing text, where the 44px floor does not apply.

### Rebuild-and-restore: the failure mode worth knowing

`buildFacets()` rewrites `#facets.innerHTML` on every change, and the graph and
legend do the same thing to their own subtrees. **A list that rewrites itself
destroys focus**, so a keyboard user gets exactly one keystroke before landing
back on `<body>`.

This is why "is it focusable?" is the wrong question to audit with. The old
facet rows *were* reachable by Tab and *did* toggle on Space — `pointer-events:
none` does not remove an input from the tab order, and Space fired a click that
bubbled to the row handler. They were unusable anyway, because the second
keystroke went nowhere.

The pattern: capture the focused row's identity before the rewrite, re-focus its
replacement after.

```js
const focused = document.activeElement;
const keep = (el.contains(focused) && focused.closest('.fitem'))
  ? focused.closest('.fitem').dataset : null;
el.innerHTML = h;
if (keep) el.querySelector(selectorFor(keep))?.focus({ preventScroll: true });
```

Apply it to any surface that regenerates its own markup — and test it by
toggling **twice**, since one toggle passes either way.

## Known dead code, safe to delete on contact

- `main.css:404-446` — `.legend-item` plus ten category colours. Zero references
  anywhere; ships on every page.
- `noblogs/index.html:9` — targets `#main-content > main`; the wrapper is
  `#content`, so it has never matched. Delete it; do **not** "fix" it, since that
  would opt noblogs into a full-bleed model we do not want.
- noblogs `--line2`; the duplicate `.nbgraph` base rule in `graph.css`.
- `tailwind.config.js`: `green-light`, `text-yellow`, `gap-gutter`; `blue`,
  `blue-500`, `blue-600` are three names for `#349CE2`.
