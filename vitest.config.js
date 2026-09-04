import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const stub = (name) =>
  fileURLToPath(new URL(`./browse/test/stubs/${name}`, import.meta.url));

export default defineConfig({
  test: {
    environment: "node",
    include: ["browse/test/**/*.test.js"],
    setupFiles: ["browse/test/setup.js"],
  },
  resolve: {
    alias: {
      "https://cdn.jsdelivr.net/npm/idb@8/+esm": stub("idb.js"),
      "https://cdn.jsdelivr.net/npm/jszip@3.10.1/+esm": stub("jszip.js"),
    },
  },
});
