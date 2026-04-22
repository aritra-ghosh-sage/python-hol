// Note 1: Unit tests for the decommissionServiceWorker utility function.
// The function is extracted from the React component so it can be tested
// with plain mock objects — no browser globals or testing-library required.
import { beforeEach, describe, expect, it, vi } from "vitest";

// Note 2: The test imports only the pure logic function, not the React component.
// This matches the "test behaviour, not implementation" principle: we verify
// that the function calls the right browser APIs with the right arguments.
import { decommissionServiceWorker } from "./ServiceWorkerDecommissioner";

// ---------------------------------------------------------------------------
// Shared mock factories
// ---------------------------------------------------------------------------

/** Creates a minimal ServiceWorkerRegistration-like mock. */
function makeRegistration() {
  return { unregister: vi.fn().mockResolvedValue(true) };
}

/** Creates a minimal ServiceWorkerContainer-like mock. */
function makeSwContainer(registrations: ReturnType<typeof makeRegistration>[] = []) {
  return {
    getRegistrations: vi.fn().mockResolvedValue(registrations),
  } as unknown as ServiceWorkerContainer;
}

/** Creates a minimal CacheStorage-like mock. */
function makeCacheStorage(cacheNames: string[] = []) {
  return {
    keys: vi.fn().mockResolvedValue(cacheNames),
    delete: vi.fn().mockResolvedValue(true),
  } as unknown as CacheStorage;
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

describe("decommissionServiceWorker", () => {
  beforeEach(() => {
    // Note 3: Clearing all mocks before each test prevents state leakage
    // between individual test cases.
    vi.clearAllMocks();
  });

  // --- Service-worker unregistration branch --------------------------------

  it("unregisters every registration returned by getRegistrations", async () => {
    const reg1 = makeRegistration();
    const reg2 = makeRegistration();
    const sw = makeSwContainer([reg1, reg2]);

    await decommissionServiceWorker(sw, null);

    expect(sw.getRegistrations).toHaveBeenCalledOnce();
    expect(reg1.unregister).toHaveBeenCalledOnce();
    expect(reg2.unregister).toHaveBeenCalledOnce();
  });

  it("resolves without error when there are no SW registrations", async () => {
    const sw = makeSwContainer([]);

    await expect(decommissionServiceWorker(sw, null)).resolves.toBeUndefined();

    expect(sw.getRegistrations).toHaveBeenCalledOnce();
  });

  it("skips SW unregistration when swContainer is null", async () => {
    // Note 4: Passing null for swContainer models environments where
    // navigator.serviceWorker is absent (e.g., older browsers, SSR context).
    await expect(decommissionServiceWorker(null, null)).resolves.toBeUndefined();
  });

  // --- Cache-storage cleanup branch ----------------------------------------

  it("deletes only caches whose name starts with the legacy prefix", async () => {
    const caches = makeCacheStorage(["hybrid-rag-v1", "hybrid-rag-v2", "unrelated-cache"]);

    await decommissionServiceWorker(null, caches);

    expect(caches.delete).toHaveBeenCalledWith("hybrid-rag-v1");
    expect(caches.delete).toHaveBeenCalledWith("hybrid-rag-v2");
    // Note 5: "unrelated-cache" must NOT be deleted — the function must be
    // surgical and leave other browser caches untouched.
    expect(caches.delete).not.toHaveBeenCalledWith("unrelated-cache");
    expect(caches.delete).toHaveBeenCalledTimes(2);
  });

  it("resolves without error when there are no caches", async () => {
    const caches = makeCacheStorage([]);

    await expect(decommissionServiceWorker(null, caches)).resolves.toBeUndefined();
  });

  it("skips cache cleanup when cacheStorage is null", async () => {
    const sw = makeSwContainer([]);

    await expect(decommissionServiceWorker(sw, null)).resolves.toBeUndefined();
  });

  // --- Combined path -------------------------------------------------------

  it("runs both unregistration and cache cleanup when both are provided", async () => {
    const reg = makeRegistration();
    const sw = makeSwContainer([reg]);
    const caches = makeCacheStorage(["hybrid-rag-v1", "keep-me"]);

    await decommissionServiceWorker(sw, caches);

    expect(reg.unregister).toHaveBeenCalledOnce();
    expect(caches.delete).toHaveBeenCalledWith("hybrid-rag-v1");
    expect(caches.delete).not.toHaveBeenCalledWith("keep-me");
  });
});
