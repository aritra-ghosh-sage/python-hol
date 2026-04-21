"use client";

// Note 1: "use client" is required because this module accesses browser-only globals
// (navigator.serviceWorker and window.caches). In Next.js App Router, any file
// that touches browser APIs must opt in to client-side execution with this directive.
import { useEffect } from "react";

// Note 2: The cache name prefix used by the removed PWA service worker (public/sw.js,
// now deleted). Only caches whose name starts with this prefix are cleared, so the
// cleanup is surgical — it never touches unrelated browser caches from other libraries.
const LEGACY_CACHE_PREFIX = "hybrid-rag-";

// ---------------------------------------------------------------------------
// Pure logic — exported for unit testing
// ---------------------------------------------------------------------------

/**
 * Unregisters all service-worker registrations for this origin and deletes any
 * cache-storage entries whose name begins with {@link LEGACY_CACHE_PREFIX}.
 *
 * Both parameters are nullable so callers can pass `null` when the corresponding
 * browser API is absent (e.g., older browsers, test environments). The function
 * degrades gracefully in either case.
 *
 * Note 3: This function is exported *only* so tests can import and invoke it
 * directly with mock objects, avoiding the need for a browser or React renderer.
 * Prefer the {@link ServiceWorkerDecommissioner} component for production use.
 *
 * @param swContainer - `navigator.serviceWorker`, or `null` if unavailable.
 * @param cacheStorage - `window.caches`, or `null` if unavailable.
 */
export async function decommissionServiceWorker(
  swContainer: ServiceWorkerContainer | null,
  cacheStorage: CacheStorage | null,
): Promise<void> {
  // Note 4: getRegistrations() returns every scope registered under this origin.
  // Unregistering all of them handles edge cases where the removed PWA may have
  // registered under multiple scopes (e.g., after a path change).
  if (swContainer) {
    const registrations = await swContainer.getRegistrations();
    await Promise.all(registrations.map((reg) => reg.unregister()));
  }

  // Note 5: Unregistering a service worker does NOT delete its cached responses.
  // The Cache Storage API must be cleared separately, otherwise stale assets
  // linger until the browser's internal eviction policy removes them.
  if (cacheStorage) {
    const names = await cacheStorage.keys();
    await Promise.all(
      names
        .filter((name) => name.startsWith(LEGACY_CACHE_PREFIX))
        .map((name) => cacheStorage.delete(name)),
    );
  }
}

// ---------------------------------------------------------------------------
// React component — headless side-effect runner
// ---------------------------------------------------------------------------

/**
 * Headless component (renders `null`) that runs the service-worker decommission
 * routine exactly once on the first client-side mount.
 *
 * **Placement**: render this component once inside the root `<body>`, alongside
 * (not wrapping) the main application children, so it has zero effect on the
 * component hierarchy or render tree shape.
 *
 * Note 6: This component is intentionally **transitional**. Once all users have
 * visited the app at least once after this release, the service worker will have
 * been unregistered for every active session and this component can be safely
 * removed from layout.tsx along with its import.
 */
export function ServiceWorkerDecommissioner(): null {
  useEffect(() => {
    // Note 7: The empty dependency array [] tells React to execute this effect
    // once after the first render and never again. Even in React 18+ Strict Mode
    // (which double-invokes effects during development), both invocations are
    // harmless — unregistering an already-unregistered service worker is a no-op.
    const sw =
      typeof navigator !== "undefined" && "serviceWorker" in navigator
        ? navigator.serviceWorker
        : null;

    const cache =
      typeof window !== "undefined" && "caches" in window ? window.caches : null;

    // Note 8: void discards the returned Promise intentionally. Errors from
    // SW unregistration are not actionable by the app — the browser will clean
    // up the registration on its own schedule if this call fails.
    void decommissionServiceWorker(sw, cache);
  }, []);

  // Note 9: Returning null means this component contributes zero DOM nodes.
  // It exists purely for its mount-time side effect — a "headless" component pattern
  // common for cross-cutting concerns such as analytics initialisation or,
  // in this case, migration cleanup.
  return null;
}
