import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    exclude: [
      "**/node_modules/**",
      "**/dist/**",
      "**/.next/**",
      "tmp-e2e/**",
      "e2e/**",
      "playwright/**",
      "**/*.spec.js",
      "**/*.spec.ts",
    ],
    include: [
      "src/**/*.{test,spec}.{ts,tsx}",
      "tests/**/*.{test,spec}.{ts,tsx}",
    ],
  },
});
