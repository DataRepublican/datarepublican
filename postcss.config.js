module.exports = {
  plugins: [
    /* First, and explicitly.
     *
     * postcss-import was already in node_modules, but only because tailwindcss
     * depends on it — and NEITHER build path was applying it:
     *
     *   build:css  runs `postcss` directly, which never handles @import itself
     *   watch:css  passes `--postcss <file>`, which makes the Tailwind CLI use
     *              THIS config instead of its own bundled pipeline
     *
     * So an @import in main.css would have passed straight through as a literal
     * at-rule: several stylesheets fetched in series, working in dev and
     * waterfalling in production. Listing it here is what makes the imports
     * actually inline, and it is why it is a direct dependency in package.json
     * rather than a hoisted one.
     */
    require('postcss-import'),
    require('tailwindcss'),
    require('autoprefixer'),
  ]
}
