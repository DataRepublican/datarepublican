/** @type {import('@playwright/test').PlaywrightTestConfig} */
const config = {
  testDir: "./tests",
  testMatch: ["**/*.spec.js"],
  timeout: 180000,
  retries: 0,
  use: {
    headless: true,
    viewport: { width: 1280, height: 720 },
    baseURL: process.env.HOST || "http://localhost:4000",
  },
  projects: [
    { name: "default" },
    {
      name: "demo",
      testMatch: ["**/browse_sankey.spec.js"],
      timeout: 600000,
      use: {
        headless: true,
        video: "on",
        screenshot: "on",
        viewport: { width: 1280, height: 720 },
      },
    },
  ],
};

module.exports = config;