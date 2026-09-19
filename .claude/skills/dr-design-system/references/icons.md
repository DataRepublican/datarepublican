# Icons

## The pack is Lucide, and it is not a new dependency

`_includes/nav.html` already inlines three Lucide glyphs — `navigation`, `user`
and `circle-dollar-sign` — at 24-box with `fill="none"`, `stroke="currentColor"`,
`stroke-width="2"` and round caps and joins. The system formalizes that rather
than introducing a pack.

```html
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
     stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M5 12h14"/><path d="M12 5v14"/>
</svg>
```

- **Inline SVG, never an icon font.** `main.css` has a leftover `.lucide-icon`
  rule with font-icon properties (`speak`, `font-variant`); it is not the pattern.
- **`stroke="currentColor"`** so an icon inherits its button's state — a pressed
  toggle turns its icon white without a second rule.
- 2px stroke at every size. Optical size: 22px glyph in a 44px button, 18px
  beside a label, 20px in a 44px icon-only control.
- Give the `<svg>` `aria-hidden="true"` when a visible label is present; when
  there is none, the **button** carries `aria-label`, not the svg.

## When an icon may replace a word

**Icon alone** — the action has a conventional glyph and no state:
zoom in `plus` · zoom out `minus` · fit/reset `maximize` · re-layout `refresh-cw`
· close `x` · collapse `chevron-left` · search `search`.

**Icon plus word** — the control carries a *state*, or is destructive or
irreversible: `Focus mode`, `Inferred links`, `Export`. A crosshair can name the
thing but cannot say whether focus is currently on or off.

**Word alone** — anything whose meaning is specific to this data:
"Target edges only", "Clear all filters", "Show more".

## Tooltips

Required on every icon-only control. A tooltip is a convenience for a mouse, not
an accessibility mechanism — the `aria-label` is what a screen reader uses, and
it must exist whether or not a tooltip does. Tooltips never carry information
that appears nowhere else.

## Why this matters on a phone

The mobile toolbar is a horizontal scroll rail along the canvas bottom edge.
Icon-only fits **six controls where three labeled ones did**, inside the same
thumb reach — which is most of the argument for doing this at all.

## Current set

`plus` · `minus` · `maximize` · `refresh-cw` · `crosshair` · `download` ·
`search` · `sliders` (filters) · `x` · `chevron-left`.

Drawn on `system-primitives` in Paper. Add to the board before adding to code.
