import { defineConfig } from "vitest/config";
import path from "path";

// Exclude Playwright e2e specs from the Vitest run — they require a running
// browser and must be executed with `playwright test`, not `vitest`.
export default defineConfig({
  test: {
    environment: "jsdom",
    exclude: [
      "**/node_modules/**",
      "**/dist/**",
      "**/tmp-e2e/**",
      "**/*.spec.js",
    ],
  },
  resolve: {
    alias: {
      // Mirror the Next.js `@/*` path alias so imports resolve in Vitest.
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
