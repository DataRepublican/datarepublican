# Components — current → target

Geometry and states are drawn on `system-primitives` and `system-surfaces` in
Paper. This file is the migration map: what each `.dr-*` class replaces, so a
partial migration stays legible to whoever arrives next.

**The adoption rule: migrate what you touched, and only what you touched.**

## Before anything else

`assets/css/main.css:86` paints every bare `<button>` slate-900 with
`min-width:65px`. Every control on the site fights it — with `!important` in
`main.css`, with `#stage button` in both tools, with `!` utilities in the banner.
Change it to `:where(button)` (zero specificity) or scope it to
`.legacy-tool button` and tag the ~20 old tool pages. Nothing else is clean until
this is done.

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
| `.dr-check` | `.fitem`, which sets `pointer-events:none` on the real checkbox and handles the click on the row. Fix natively: `<label>` around `<input>`, inside `<fieldset><legend>` |
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

Tabs, chips, facet rows, legend rows and the clear-all control are all
non-focusable `<div>`/`<span>` with onclick. Focus styling exists on exactly one
selector site-wide (`.dr-sheet:focus-visible`); `#search:focus` *removes* the
outline. Tap targets under 44px: `.loadmore` ~39, `.fitem` ~24, `.lgrow` ~19,
`.chip` ~25, legend `.row` ~19.

## Known dead code, safe to delete on contact

- `main.css:404-446` — `.legend-item` plus ten category colours. Zero references
  anywhere; ships on every page.
- `noblogs/index.html:9` — targets `#main-content > main`; the wrapper is
  `#content`, so it has never matched. Delete it; do **not** "fix" it, since that
  would opt noblogs into a full-bleed model we do not want.
- noblogs `--line2`; the duplicate `.nbgraph` base rule in `graph.css`.
- `tailwind.config.js`: `green-light`, `text-yellow`, `gap-gutter`; `blue`,
  `blue-500`, `blue-600` are three names for `#349CE2`.
