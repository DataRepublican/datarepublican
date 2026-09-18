/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './_includes/**/*.{html,js}',
    './_layouts/**/*.{html,js}',
    './_posts/**/*.{html,md}',
    './_pages/**/*.{html,md}',
    './docs/**/*.{html,js,md}',
    './[^_]**/*.{html,js,md}',  // Match all non-underscore dirs
    './*.{html,js}',
  ],
  safelist: [
    'min-h-[75vh]',
    'left-[initial]',
    '-m-1',
    'list-disc',
    'list-inside',
    'space-y-4',
    'md:w-[300px]',
    'md:w-[60px]',
    'bottom-4',
    'md:ml-12',
    'max-h-[calc(100vh-2rem)]',
    'max-h-16',
    'md:rounded',
    'md:rounded-lg',
    // '!hidden',
    // '-mb-4',
    // '-my-0.5',
    // '-mr-1',
    // 'animate-pulse',
    // 'block',
    // 'bg-blue-100',
    // 'bg-gray-300',
    // 'bg-none',
    // 'bg-slate-900',
    // 'bg-white',
    // 'border-0',
    // 'border-blue-600',
    // 'capitalize',
    // 'col-span-2',
    // 'col-span-3',
    // 'col-span-5',
    // 'cursor-pointer',
    // 'flex-[0_0_auto]',
    // 'float-right',
    // 'font-medium',
    // 'font-semibold',
    // 'gap-0.5',
    // 'gap-2',
    // 'gap-4',
    // 'gap-x-2',
    // 'gap-y-1.5',
    // 'gap-y-1',
    // 'grid-cols-3',
    // 'grid-cols-5',
    // 'group',
    // 'group-hover',
    // 'group-hover:opacity-100',
    // 'h-5',
    // 'h-full',
    // 'hidden',
    // 'hover:opacity-100',
    // 'inline-flex',
    // 'items-end',
    // 'justify-between',
    // 'justify-center',
    // 'justify-end',
    // 'justify-start',
    // 'leading-9',
    // 'lg:flex',
    // '!list-decimal',
    // 'max-w-2xl',
    // 'mb-0',
    // 'mb-12',
    // 'md:block',
    // 'md:col-span-2',
    // 'md:col-span-3',
    // 'md:col-span-5',
    // 'md:flex-col',
    // 'md:float-right',
    // 'md:gap-y-1.5',
    // 'md:gap-2',
    // 'md:gap-4',
    // 'md:grid-cols-3',
    // 'md:items-center',
    // 'md:items-start',
    // 'md:justify-between',
    // 'md:mb-0',
    // 'md:ml-4',
    // 'md:mr-2',
    // 'md:mx-0',
    // 'md:mx-auto',
    // 'md:px-0',
    // 'md:self-end',
    // 'md:text-base',
    // 'md:text-left',
    // 'md:w-auto',
    // 'min-h-[44px]',
    // 'md:min-h-[50vh]',
    // 'min-w-[65px]',
    // 'min-h-screen',
    // 'ml-2',
    // 'mt-0',
    // 'mt-1',
    // 'mt-4',
    // 'my-2',
    // 'opacity-50',
    // 'opacity-75',
    // 'pb-1',
    // 'pb-2',
    // 'pb-4',
    // 'pt-2',
    // 'pt-3',
    // 'pt-8',
    // 'py-8',
    // 'px-3',
    // 'rounded',
    // 'rounded-full',
    // 'self-end',
    // 'size-2',
    // 'size-3',
    // 'size-4',
    // 'size-5',
    // 'size-6',
    // 'size-24',
    // 'text-[15px]',
    // 'text-base',
    // 'text-center',
    // 'text-green-600',
    // 'text-orange-500',
    // 'text-white',
    // 'w-16',
    // 'w-screen',
    // You can also use patterns
    // 'bg-[0-9]+',
  ],
  theme: {
    extend: {
      colors: {
        transparent: 'transparent',
        current: 'currentColor',

        // Brand. Used throughout the tool interiors — do not repurpose.
        navy: '#252739',
        blue: '#349CE2',
        'blue-500': '#349CE2',
        'blue-600': '#349CE2',
        yellow: '#E2D134',
        red: '#EF3E28',
        'green-light': '#34E297',
        green: '#19B270',

        // v2 chrome, measured from the Figma frames. The mocks define no
        // Figma variables — the fills are raw — so these values are the
        // source of truth and live here rather than being reverse-engineered
        // from the file each time.
        surface: '#E5E7EB',   // page ground
        card: '#FFFFFF',      // card fill
        rule: '#B0B0B0',      // hairlines and card borders
        ink: '#111111',       // body text
        'ink-strong': '#000000', // wordmark, card titles
        'ink-muted': '#5A5A5A',  // taglines, meta
        band: '#E9B408',      // the promo/alert band

        /* The tool chrome. Drawn on `system-foundations` in Paper — read the
           values there, do not invent them here.

           Two things these encode that are not obvious from the hexes:

           The old tool greys are WARM (#E2E2DD, #F1F1EC, #F7F7F3, #D5D5CE) and
           `surface` above is COOL. That split is why the tools read as a
           different site pasted onto the page, so every replacement below is
           cool.

           And chrome has no hue. The old accent was #C0392B, which is
           byte-identical to the `anarchist` swatch on the map legend — so
           "selected" and "anarchist" were the same colour. `accent` is near-ink
           instead: selected reads as darker, never as a colour, which is the
           only way chrome stays out of the way of thirteen encoded categories.
           Red now lives only in the data namespace below. */
        accent: '#252739',            // selected, active, pressed, focus ring
        'accent-tint': '#DEE0E8',     // selected chips and legend rows
        'accent-tint-line': '#A9AEBF',
        'ink-faint': '#6B7280',       // counts, hints. 4.5:1 on white
        line: '#D3D7DE',              // decorative hairlines
        /* Interactive borders, deliberately darker than `rule`. WCAG 1.4.11
           wants 3:1 for a UI component boundary; #B0B0B0 is ~2.1:1 and fails.
           `rule` stays for the masthead rule and the sheet grip, where it is
           decorative rather than a control edge. */
        'line-strong': '#878D99',
        fill: '#EFF1F4',              // tracks, hover
        'fill-quiet': '#F7F8FA',
        'legal-border': '#E4C9A0',
        'legal-fill': '#FBF3E4',
        'legal-ink': '#6B5A3E',
      },

      /* Two families, two jobs. Libre Franklin is the content voice — headlines,
         body, card titles, panel prose. Helvetica is the interface voice —
         button labels, chips, field text, counts, every label. `body` sets the
         content family; `font-ui` is opt-in on controls. */
      fontFamily: {
        content: ['"Libre Franklin"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        ui: ['"Helvetica Neue"', 'Helvetica', 'Arial', 'sans-serif'],
      },

      // A named ramp, so the 15px body / 13px meta sizes stop being repeated
      // as arbitrary values. Line heights are paired in.
      fontSize: {
        display: ['3.4375rem', { lineHeight: '1', letterSpacing: '-0.05em' }], // 55px wordmark
        title: ['1.5rem', { lineHeight: '1.15', letterSpacing: '-0.02em' }],
        'card-title': ['1.375rem', { lineHeight: '1.2', letterSpacing: '-0.02em' }],
        lede: ['1.0625rem', { lineHeight: '1.45', letterSpacing: '-0.01em' }],
        body: ['1rem', { lineHeight: '1.5', letterSpacing: '-0.01em' }],
        meta: ['0.8125rem', { lineHeight: '1.4' }],

        /* Added for the tools, which live between 11 and 14px and had nothing
           to reach for: the ramp jumped 13 → 16.

           `label` is every interface label, eyebrow and column header. It is
           sentence case, never uppercase — an uppercase 11px label step used to
           exist and was retired when the labels stopped shouting, because 11px
           mixed case fails the 12px floor below.

           Floors: nothing under 11px anywhere; 12px minimum for mixed case;
           13px minimum for anything read as a sentence. The disclaimer is the
           one piece of text here with legal consequence and must never be the
           smallest type on the page. */
        label: ['0.75rem', { lineHeight: '1rem' }],       // 12px
        caption: ['0.75rem', { lineHeight: '1.4' }],      // 12px
        dense: ['0.875rem', { lineHeight: '1.45', letterSpacing: '-0.005em' }], // 14px
        section: ['1.125rem', { lineHeight: '1.25', letterSpacing: '-0.02em' }], // 18px
      },

      letterSpacing: {
        display: '-0.05em',
        title: '-0.02em',
        body: '-0.01em',
      },

      spacing: {
        gutter: '1.25rem', // 20px — the mock's page gutter
        tap: '2.75rem',    // 44px — the minimum tappable dimension
        'tap-sm': '2rem',  // 32px — desktop-only, inside a panel or toolbar
      },

      borderRadius: {
        sm: '0.375rem',    // 6px — tags, callouts
        card: '0.5rem',
        lg: '0.75rem',     // 12px — KPI tiles, popovers
        sheet: '1rem',     // 16px — the bottom sheet's top corners
        pill: '9999px',
      },

      boxShadow: {
        hair: '0 1px 2px rgba(0,0,0,.05)',
        raise: '0 2px 8px rgba(0,0,0,.08)',   // anything floating over a canvas
        lift: '0 8px 24px rgba(0,0,0,.12)',
        sheet: '0 -4px 24px rgba(0,0,0,.22)',
      },

      /* One scale for the whole site, and nothing above 100. The gaps exist so
         a new layer can land between two without a renumber.

         The rule this encodes: a vendored stylesheet that numbers its own layers
         in the hundreds — Leaflet's panes run 400/800/1000 — is never out-bid,
         it is CONTAINED with `isolation: isolate` on the element wrapping it.
         Out-bidding is what produced the numbers this replaces: noblogs was
         running 600/850/900/1000/1100/1150/1200 and its mobile sheet was still
         underneath the map, because the map's 1000 was never in the same
         stacking contest. */
      zIndex: {
        raised: '10',
        'canvas-ui': '20',   // toolbar, legend, search inside an isolated canvas
        sticky: '30',        // tool header
        'nav-veil': '40',
        nav: '50',
        scrim: '55',
        panel: '60',         // sheet / drawer
        popover: '70',
        'modal-scrim': '80',
        modal: '90',
        skip: '100',
      },

      // The page measures. The active shell is published as --column-max in
      // main.css so the banner, masthead, nav and content all line up on the
      // same number; which of `wide` and `snug` is active depends on the
      // viewport, not on the page.
      maxWidth: {
        column: '64rem',  // 1024px — reading column for the narrative pages
        wide: '100rem',   // 1600px — the shell from 1600px up
        snug: '87.5rem',  // 1400px — the shell below 1600px
        prose: '52rem',   // 832px — the measure shared by About and Donate
      },

      outlineColor: theme => ({
        ...theme('colors')
      })
    },
  },
  plugins: [
    require('@tailwindcss/container-queries'),
    require('@tailwindcss/typography'),
  ],
} 