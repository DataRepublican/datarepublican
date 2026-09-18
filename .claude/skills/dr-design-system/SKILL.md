---
name: dr-design-system
version: 1.0.0
description: >-
  The DataRepublican design system — tokens, the .dr-* component layer, the
  z-index scale, the icon set and the shell measure. Read this BEFORE editing
  assets/css/main.css, assets/css/tokens.css, assets/css/components/*,
  tailwind.config.js, assets/js/sheet.js, or the inline <style>/<script> blocks
  in noblogs/ or dsa-explorer/. Carries the traps that have cost real time in
  this repo: Tailwind's @layer purge, classes glued to Liquid tags, tools
  styling bare header/aside/main/#panel, docs/ being production, and vendored
  z-index escaping into the root stacking context. The visual source of truth is
  a Paper file, linked below — do not invent values, read them.
---

# DataRepublican design system

## The source of truth is not this file

The system is drawn in **Paper**, file `01M1HN443QBKENVTJXMDDY96K7`, page `p-2-0`.
Four boards, in order:

| Board | What it settles | Link |
|---|---|---|
| `system-foundations` | Palette with roles, type scale, the two findings the direction rests on | [open](https://app.paper.design/file/01M1HN443QBKENVTJXMDDY96K7/p-2-0/6C2-0) |
| `system-primitives` | Nine controls × six states, plus the icon set | [open](https://app.paper.design/file/01M1HN443QBKENVTJXMDDY96K7/p-2-0/6IN-0) |
| `system-surfaces` | Card, tile, panel, sheet, legend, toolbar, callout, empty, loading | [open](https://app.paper.design/file/01M1HN443QBKENVTJXMDDY96K7/p-2-0/6OG-0) |
| `system-layout` | Shell measure, three layout modes, the z scale | [open](https://app.paper.design/file/01M1HN443QBKENVTJXMDDY96K7/p-2-0/6ZS-0) |

Design tokens live **in that file** as Paper tokens and are mirrored into
`tailwind.config.js`. Read them with the Paper MCP (`get_tokens`,
`get_computed_styles`, `get_jsx`) rather than eyeballing a screenshot. If a value
you need is not in the file, it is not in the system yet — add it there first.

The five artboards named `noblogs-*` and `dsa-*` on the same page are **captures
of the app as it was in September 2026**, kept as the "before". Do not read
current values from them.

## The direction, in one line

A cool, near-monochrome instrument — fog ground, near-black chrome, white data
surfaces — so the only saturated colour on screen is the data itself.

Two findings hold it up, and both are measurable:

1. The page ground `#E5E7EB` is **cool**; every grey inside the tools is **warm**
   (`#E2E2DD`, `#F1F1EC`, `#F7F7F3`, `#F0F0EA`, `#D5D5CE`, …). That temperature
   split is why the tools read as a different site pasted onto the page.
2. The old chrome accent `#C0392B` is **byte-identical to the `anarchist`
   category swatch**. Chrome was colliding with data.

Hence: **chrome has no hue.** `--color-accent` is `#252739`, a near-ink navy.
Selected reads as *darker*, never as *a colour*. Red survives only as a data
value — doxxing flags, target edges, the anarchist swatch — never as chrome.

## The nine prohibitions

Each of these has already happened here, or is one edit away.

1. **Never put a `.dr-*` rule inside `@layer components`.** Tailwind drops a
   layered rule whose selector it cannot find in scanned HTML, and every `.dr-*`
   class is written at runtime by JS. It has happened: `.dr-canvas` and
   `.dr-controls` vanished entirely and `.dr-sheet__grip` lost its base
   `display:none`, so the drag handle appeared on desktop.
   **Rule: if it is in `assets/css/components/`, it is outside a layer.**
   Detect: `curl -s localhost:4000/assets/css/styles.css | grep -F 'dr-sheet__grip'`

2. **Never type a literal hex, px or rem into a tool's CSS.** `tailwind.config.js`
   `theme` is the source; `tokens.css` derives `--dr-*` from it with `theme()`;
   tools read `var(--dr-*)`. A literal guarantees a half-finished restyle.

3. **Never add a `:root` block to a tool.** Scope it — `body[data-view]` for
   noblogs, `#app` for dsa-explorer. An unlayered `:root` inside a tool's
   `<style>` outranks `bg-surface` on `<body>` and changes the site masthead's
   background on that page. Documented at `noblogs/index.html:10-14`.

4. **Never out-bid a vendored z-index. Contain it.** `isolation: isolate` on the
   element wrapping the vendor's DOM. Leaflet numbers its panes 400/800/1000 and
   is entitled to — it assumes it owns a stacking context. It did not have one,
   and the mobile sheet rendered *under* the map. **No repo-authored `z-index`
   above 100, ever.**

5. **Never style a bare `header`, `aside`, `main`, `#panel` or `#search` from a
   tool.** The site masthead is a `<header>` and precedes the tool's in the DOM;
   the banner is an `<aside>`. Both tools did this and reshaped the masthead from
   across the page. Scope to an id (`#nb-header`, `#dsa-header`) or a root class
   (`.nbgraph`). `tests/test_review_regressions.spec.js` guards it — do not weaken it.

6. **Never write a class glued to a closing Liquid tag.** It is swallowed into one
   candidate and no rule is generated, silently. Assign classes to a variable and
   interpolate. See `_includes/nav.html`.
   Detect: `curl -s localhost:4000/assets/css/styles.css | grep -F 'your-class'`

7. **Never defer the tools bundle, make it a module, or move it out of `<head>`.**
   Both tool pages call `DRSheet.attach` from an inline `<script>` in the **body**,
   which runs during parsing, before any deferred script. `window.DRSheet` must
   exist by then.

8. **Never replace `DRSheet` with a dialog machine.** See `references/contracts.md`.
   It carries detents, pointer-drag with documented thresholds, a focus trap and a
   `display:contents` desktop-inert mode. Two consumers depend on its exact
   contract and one encodes a focus bug that was already fixed once.

9. **No headless component library, and no JS bundler.** Zag.js was chosen and
   then dropped, on evidence: four of the five machines planned for it — tabs,
   collapsible, toggle-group and the independent `aria-pressed` toggles — were
   built natively in a few dozen lines each and are covered by passing specs, and
   the filter popover already returns focus to its trigger on Escape. What was
   left was floating-ui's flip/shift on one popover and a combobox nobody asked
   for. Against that: ~40KB, a bundler this repo does not have, a committed
   `dist/`, a CI check that it matches source, and a fifth entry on CLAUDE.md's
   "when a change does not show up" list — the failure this repo loses afternoons
   to. **Revisit only for a control that is genuinely hard to hand-roll**: a real
   combobox with `aria-activedescendant`, a menu with typeahead, a date picker.
   Native semantics first — `<details>`, `<fieldset>`, `<label>`, `<button
   aria-pressed>` — every time.

## Three standing instructions

- **The adoption rule.** Collapsing every tool onto shared CSS is the direction,
  not a requirement. When you open a file for any reason, migrate what you
  touched — and only what you touched. Do not rewrite a working tool to match the
  spec. `references/components.md` carries the current → target table so a partial
  migration stays legible.
- **The verify loop** is `yarn start`, wait ~20s for first boot, then
  `npx playwright test`. Never hand-roll `jekyll serve`: `_config.yml` says
  `destination: docs` and **`docs/` is production**.
- **Check the artifact, not the source.** This repo's chronic failure is correct
  source with a stale artifact, and there is more than one artifact.

## Reference files

- `references/tokens.md` — the palette, scales, and the `theme()` → `:root` direction
- `references/components.md` — the `.dr-*` catalogue, current → target per component
- `references/icons.md` — Lucide, and when an icon may replace a word
- `references/contracts.md` — APIs a refactor must not break
- `references/traps.md` — each trap with a reproduction and a detection command
