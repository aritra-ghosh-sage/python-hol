import { defineConfig } from "vitest/config";
import path from "path";

// WHY: This file configures Vitest for unit tests only.
// The `tmp-e2e` folder contains Playwright end-to-end specs that must be run
// with the Playwright CLI (not Vitest).  Without the `exclude` entry below,
// Vitest would attempt to execute them and fail because Playwright's test()
// API is not available in the Vitest runtime.
export default defineConfig({
  test: {
    environment: "jsdom",
    exclude: [
      "**/node_modules/**",
      "**/dist/**",
      // Playwright e2e specs live here; they require a running browser and
      // should be run via `playwright test`, not `vitest`.
      "**/tmp-e2e/**",
      "**/*.spec.js",
    ],
  },
  resolve: {
    alias: {
      // Mirror the Next.js `@/*` path alias so imports like `@/lib/types`
      // resolve correctly inside Vitest without needing a Next.js runtime.
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
