# Automated Tests
`python testBuilder.py` builds a set of script to test every index.html file.

## Setup
``` sh
npm install —save-dev @playwright/test
npx playwright install
```

## Running Tests
``` sh
npx playwright test
npx playwright test --ui
npx playwright test --reporter=list
HOST=https://57.datarepublican.com npx playwright test
npx playwright test --last-failed
npx playwright test --last-failed --headed

## Browse Sankey demos (video)

Playwright records WebM when `video: "on"` (the `demo` project). Jekyll must be up (`npm start`) and `/browse` data loaded.

```sh
npx playwright test tests/browse_sankey.spec.js --project=demo
```

Clips land under `test-results/**/video.webm` **even when the test fails**. `npm run demo:browse` is the same. Default `npx playwright test` stays headless and does not record.

Empty `/browse/` has no Sankey nodes until a preset. The demo spec waits for the loaded empty state, then **Show Controls** (not Show Presets) and Replace + Uniparty.

```