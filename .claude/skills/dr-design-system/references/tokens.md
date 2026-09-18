# Tokens

Read the live values from Paper (`get_tokens` on file `01M1HN443QBKENVTJXMDDY96K7`).
This file records the **roles and the direction**, which a value list cannot.

## The direction: config → `:root`, never the reverse

`tailwind.config.js` `theme` is the single source. `assets/css/tokens.css`
publishes it to `:root` as `--dr-*` using `theme()`. Two surfaces read the same
numbers:

- `_includes/` chrome → Tailwind utilities (`bg-surface`, `text-meta`, `px-gutter`)
- tool CSS, `graph.css`, runtime-generated classes → `var(--dr-*)`

This is not a new idea here. `main.css` already does it:

```css
:root { --column-max: theme('maxWidth.snug'); }
```

That line is the whole argument. Rejected alternatives: `:root` as source (breaks
`fontSize` tuples and `@media` widths); a shared `tokens.js` (a build stage for
what `theme()` gives free); maintaining both by hand (guaranteed drift).

`tokens.css` is **outside `@layer`** — `:root` is not a class Tailwind scans for.

## Colour

### Chrome — no hue

| Token | Role |
|---|---|
| `surface` `#E5E7EB` | page ground. Cool. Unchanged from what shipped |
| `panel` `#FFFFFF` | cards, drawers, sheets |
| `ink` `#111111` | body text |
| `ink-muted` `#5A5A5A` | meta |
| `ink-faint` `#6B7280` | counts, hints. Passes 4.5:1 |
| `accent` `#252739` | selected, active, pressed, focus ring |
| `accent-tint` `#DEE0E8` | selected chips and legend rows |
| `accent-tint-line` `#A9AEBF` | border on a tinted chip |
| `line` `#D3D7DE` | decorative hairlines |
| `line-strong` `#878D99` | borders of **interactive** elements |
| `fill` `#EFF1F4` | tracks, hover |
| `fill-quiet` `#F7F8FA` | quiet grounds |
| `band` `#E9B408` | the promo/alert band **only**. Never chrome |

Two non-negotiables:

- **`line-strong` must clear 3:1 on white.** WCAG 1.4.11 governs UI component
  boundaries. The old `rule` `#B0B0B0` is ~2.1:1 and fails. Keep `rule` for the
  masthead rule and the sheet grip, where it is decorative.
- **Every muted grey in the old tools fails 4.5:1** — `#999` is 2.85:1. `#888`,
  `#9a9ea6` and `#a8aab0` likewise. Use `ink-muted` or `ink-faint`.

### Data — the separate namespace

The graph and map category hexes (`--dr-data-*`) are versioned but **not
themeable**. The JS palettes in `noblogs/graph/graph.js` and
`dsa-explorer/index.html` hardcode the same values; changing one without the
other makes the legend lie about the picture.

**A restyle must not touch them.** Chrome tokens and data tokens never merge.

## Type

Nine steps. `label` and `body`+ in the UI font; everything else in content font.

| Token | px | Job |
|---|---|---|
| `label` | 12 | every interface label, eyebrow, column header, tag, KPI caption |
| `caption` | 12 | dense meta, counts |
| `meta` | 13 | button labels — the reading floor |
| `dense` | 14 | card titles, panel body. **The rung that did not exist** |
| `body` | 16 | inputs, prose, empty states |
| `lede` | 17 | panel headings |
| `section` | 18 | tool titles |
| `card-title` | 22 | KPI values |
| `title` / `display` | 24 / 55 | page headings, wordmark |

Rules: **nothing below 11px anywhere**; 12px minimum for mixed case; 13px minimum
for anything read as a sentence. The disclaimer is the one piece of text with
legal consequence and must never be the smallest type on the page.

> The old scale had a `micro 11 / uppercase / +0.04em` step. It was retired when
> labels stopped being uppercase — 11px mixed case fails the 12px rule. Removing
> a mannerism removed a token.

## Fonts

- `--font-content` **Libre Franklin** — headlines, body, card titles, panel prose
- `--font-ui` **Helvetica Neue / Helvetica / Arial** — button labels, chips, field
  text, counts, every label and eyebrow

**Labels are never uppercase.** Sentence case, weight 600, UI font.

## Radius, shadow, space

Radius, five steps: `sm` 6 · `card` 8 · `lg` 12 · `sheet` 16 · `pill` 9999.
Retired: 4→6, 10→8, 14→8, **20→pill** (a 20px radius on a 35px field *is* a pill,
drawn inconsistently).

Shadow, four: `hair` · `raise` (anything floating over a canvas) · `lift` ·
`sheet`. Retired outright: `0 1px 5px rgba(0,0,0,.4)` — 40% alpha is a Leaflet
default and 4× darker than anything else here.

Spacing keeps `gutter` 1.25rem and `tap` 2.75rem, adds `tap-sm` 2rem. Snap
padding and gap to 2 / 4 / 6 / 8 / 12 / 16 / 24 / 32 / 48.

## Deduplication to carry out on contact

- noblogs `:root`: `--hi` duplicates `--accent`; `--med` duplicates `--gold` (so
  `.kpi.a` and `.kpi.d` render identically); `--line2` is declared and never used.
- dsa-explorer `:root`: `--party`, `--state`, `--veneer`, `--center`, `--line` are
  declared and used by nothing — the same hexes are repeated as literals in its JS.
  Do not delete them; have the JS read them once via `getComputedStyle` at boot.
