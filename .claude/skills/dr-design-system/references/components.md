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

## Surfaces

| Class | Replaces / decision |
|---|---|
| `.dr-card` | drops the `translateY(-2px)` hover (it makes an auto-fill grid shimmer); becomes an `<a>` — today it is a `<div>` with onclick, so no card is keyboard-reachable or openable in a new tab |
| `.dr-tile` | KPI values lose their six colours. Two of the six were already identical because `--gold` and `--med` are the same hex |
| `.dr-panel` | three layouts. **Docked column wins** over noblogs' fixed overlay: an overlay + scrim dims the map you just clicked, the failure the sheet exists to fix. `clamp(320px, 30vw, 392px)` absorbs 340/370/392 and deletes the stray `@media(max-width:820px)` with its 768–820 dead zone |
| `.dr-sheet` | keep as-is structurally. Gains a visible title and keyboard detent control |
| `.dr-popover` | the hand-rolled facet sheet + `#nb-facetscrim` + `place()` |
| `.dr-legend` | three legends. **dsa's bar + expandable key wins** — the map card covers a third of a 390px screen and toggles from a bare `<h4>`; the graph card has no collapse at all. Swatch *shape* stays a variable so the map keeps circles |
| `.dr-controls` | two near-identical toolbars in two files. `main.css:274-286` already has this, correct and unused — adopt it, but only when a tool's shell is open for other reasons |
| `.dr-callout` | three amber disclaimers at 10 / 10.5 / 11px with different line-heights. **Goes up to 13px**, and becomes a real `<details>` with a 44px summary on phones — which also removes one of the two reasons the header is measured at runtime |
| `.dr-empty` | four empty states at 13px → 16px, and gains the action that resolves them |
| `.dr-loading` | gains `aria-live="polite"`; today the map veil is silent and its error state has no retry |

## Detail panel anatomy — `.dr-detail`

`__label` collapses **eight** uppercase-label styles into one (12px, sentence
case, UI font, `ink-faint`). `__note` keeps noblogs' left rule and drops dsa's
fill — a fill *and* a rule *and* a half-radius is three decorations doing one job.
Also `__header`, `__kv`, `__srclist` (keep dsa's `›` prefix), `__connlist`.

## Accessibility debt this clears

Tabs, chips, legend rows and the clear-all control are non-focusable
`<div>`/`<span>` with onclick. Focus styling exists on exactly one selector
site-wide (`.dr-sheet:focus-visible`); `#search:focus` *removes* the outline.
Tap targets under 44px: `.loadmore` ~39, `.lgrow` ~19, `.chip` ~25, legend
`.row` ~19. (`.fitem` was ~24 and is done.)

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
