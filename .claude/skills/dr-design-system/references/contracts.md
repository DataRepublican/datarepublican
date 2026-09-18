# Contracts a refactor must not break

Every entry here is load-bearing and non-obvious. Most encode a bug that was
already fixed once.

## `window.DRSheet` — `assets/js/sheet.js`

The shared bottom sheet. **Two consumers**: `noblogs/index.html` and
`dsa-explorer/index.html`. Do not replace it with a dialog machine.

```js
DRSheet = { attach(el, {label, detent, onClose}) -> handle, isMobile(), DETENTS }
handle  = { el, open(detent?), close(), isOpen(), setDetent(d), isMobile() }
DETENTS = { peek: 0.32, half: 0.55, full: 0.92 }   // fractions of innerHeight
```

**It wraps, it does not nest.** `attach()` inserts a `div.dr-sheet` *around* the
host element. Both tools do `panel.innerHTML = …` on every interaction, so
anything inserted as a child is destroyed on the first tap. The grip and close
button live in the wrapper for this reason.

**`display: contents` is load-bearing.** At desktop the wrapper vanishes from
layout so `#panel` stays a direct grid child. `test_dsa_explorer_mobile.spec.js`
asserts the panel is the right-hand column at 1280px. Portalling breaks both the
test and the layout.

**`lastFocused` is captured only on the first open of a run.** dsa-explorer calls
`open()` on *every* node tap; re-capturing made `close()` restore focus to a
closed sheet. There is a comment in the file about it. Any rewrite that re-runs
focus capture per `open()` reintroduces that bug.

**Drag thresholds**, grip-only, Pointer Events: `dy > 120` steps down a detent or
closes from `peek`; `dy < -80` steps up; upward drag is rubber-banded `dy/3`.
Asymmetric on purpose. No velocity detection — a fast short flick will not close.

**noblogs drives it indirectly**: a `MutationObserver` on `#panel`'s class mirrors
the tool's own `.on` onto `sheet.open()` / `sheet.close()`. Calling the sheet
directly is the improvement, but `openModal`/`closeModal` must stay the single
entry point either way.

### `onClose` is not a deselect hook

**The sheet is a view of the selection, not the selection itself.** Dismissing it
must leave the underlying visualization exactly as it was — same fade, same
selected element, same camera.

dsa-explorer got this wrong and it shipped. Its `onClose` ran
`cy.elements().removeClass('faded nbr sel')`, which is the focus-OFF branch of
its background-tap handler, applied unconditionally — including in focus mode,
which is the default. So on a phone you tapped a node to read it, and closing
what you were reading snapped the whole network back to full strength and lost
the walk.

Two things to take from it:

- The tool's real deselect gesture was **conditional** (focus mode re-applies the
  ring; only focus-off clears) and the close handler borrowed one branch of it.
  If you find yourself copying a line out of another handler into `onClose`, that
  is the smell.
- "Restoring" state on close is also wrong when restoring **moves** something.
  `applyFocus()` animates the camera over 420ms, so re-applying it on dismiss
  would shift the view the user had just positioned.

noblogs is fine: its `onClose` calls `closeModal()`, which only clears its own
`.on` classes and `SEL`, and touches neither the map nor the graph.

Test a dismissal by **both** paths. The close button and a swipe are different
code paths, and a swipe from `half` steps to `peek` rather than closing — a
single drag never reaches `close()` at all.

## noblogs view tabs

`noblogs/index.html` calls `document.querySelector('.tab[data-v="…"]').click()`
internally in two places, and `test_noblogs_mobile.spec.js` clicks
`.tab[data-v="map"]` directly. If tabs become a Zag tablist: wire the view change
from `onValueChange`, replace the internal `.click()` calls with `api.setValue()`,
and **leave the click path working** so no spec needs editing.

## noblogs cross-filter

`filtered()` feeds three consumers at once — the card grid, the map's `setHosts`,
and the graph's host set. A facet toggled anywhere must still filter all three.
This is the single most valuable behaviour not to break, and it is what made the
unreachable Filters button a real bug rather than a cosmetic one.

## Ids the specs assert

`#nb-header` (sticky), `#panel`, `#gpanel`, `#legToggle` (visible, ≥44px),
`#legend .legchips` (hidden → visible), `#mapcanvas`, `#maploading`,
`header.page-column` (must stay `position: static`). Preserve them through any
restructure.

## Test expectations that encode product decisions

- `test_noblogs_mobile.spec.js` — landing view is the **map**; a `?view=dash`
  deep link must not fetch `map_data.js`, `/map.js` or leaflet.
- Ten `.card` waits use `state: 'attached'` because the landing view hides
  `#dashview`. The three that ask for `visible` navigate to `?view=dash`.
- `test_review_regressions.spec.js` — the masthead stays a plain static block on
  `/`, `/noblogs/`, `/dsa-explorer/`, `/browse/`, `/about/`; the shell measure
  follows the viewport (1280 → 1280, 1500 → 1400, 1600 → 1600, 2000 → 1600).

## Payload figures, correctly stated

Over the wire, gzipped: `data.index.json` **3.1 MB** (fetched on every view,
unconditionally), `data.detail.json` **2.3 MB** (prefetched after paint),
`map_data.js` **0.8 MB** (on Map activation). The uncompressed 3.68 MB figure for
`map_data.js` appears in older comments and overstates the cost by ~4×.
