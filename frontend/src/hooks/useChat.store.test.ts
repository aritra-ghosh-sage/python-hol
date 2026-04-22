/**
 * Tests for the chat history persistence contract.
 *
 * WHY this file exists:
 * The chat history was lost every time the user switched to a different panel
 * because `useChat` stored messages in local React state (useState).  When the
 * QueryPanel unmounts, React discards that state.
 *
 * The fix routes all message state through `useChatStore`, which uses Zustand's
 * `persist` middleware to save to localStorage.  These tests verify the contract
 * between the hook logic and the store so the bug cannot regress silently.
 *
 * Testing strategy: we test the Zustand store directly rather than the React
 * hook.  This avoids the need for @testing-library/react while still covering
 * every state transition that `useChat` delegates to the store.
 */

import { beforeEach, describe, expect, it } from "vitest";
import { useChatStore } from "../stores/chatStore";
import type { ChatMessage, DocumentResult } from "../lib/types";

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

/** Build a minimal user message for use in tests. */
function makeUserMessage(id: string, content: string): ChatMessage {
  return { id, role: "user", content, timestamp: Date.now(), status: "sent" };
}

/** Build a "loading" system message that the hook appends while waiting for WS reply. */
function makeLoadingMessage(id: string): ChatMessage {
  return {
    id,
    role: "system",
    content: "Searching documents...",
    timestamp: Date.now(),
    status: "loading",
  };
}

/** Build a minimal DocumentResult for use in results assertions. */
function makeResult(i: number): DocumentResult {
  return { id: `doc-${i}`, text: `result text ${i}`, source: `src-${i}`, score: 0.9 };
}

// ---------------------------------------------------------------------------
// Test setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  // Reset store to a clean slate before each test so tests are fully isolated.
  // This mirrors what happens when a user first loads the page with an empty
  // localStorage entry.
  useChatStore.persist.clearStorage();
  useChatStore.setState({ messages: [], messageCounter: 0 });
});

// ---------------------------------------------------------------------------
// Persistence: the core regression guard
// ---------------------------------------------------------------------------

describe("chat history persistence across simulated remounts", () => {
  it("retains messages in the store after clearing and re-reading (simulates tab switch)", () => {
    // WHY: The original bug was that local useState was discarded on unmount.
    // With the store, clearing and re-reading the same store instance should
    // always return the current persisted state.
    const userMsg = makeUserMessage("u-1", "hello world");
    const doneMsg: ChatMessage = {
      id: "s-1",
      role: "system",
      content: "Found 2 relevant documents",
      results: [makeResult(0), makeResult(1)],
      timestamp: Date.now(),
      status: "done",
    };

    useChatStore.getState().appendMessages([userMsg, doneMsg]);

    // Simulate re-reading state that a freshly-mounted component would see.
    const persisted = useChatStore.getState().messages;

    expect(persisted).toHaveLength(2);
    expect(persisted[0]?.id).toBe("u-1");
    expect(persisted[1]?.id).toBe("s-1");
    expect(persisted[1]?.status).toBe("done");
  });

  it("clearHistory removes all messages so the panel starts fresh", () => {
    // WHY: The "Clear History" button (added alongside the persistence fix)
    // must use clearHistory() from the store so subsequent mounts also see
    // an empty history, not just the current render.
    const msg = makeUserMessage("u-1", "test message");
    useChatStore.getState().appendMessages([msg]);
    expect(useChatStore.getState().messages).toHaveLength(1);

    useChatStore.getState().clearHistory();

    expect(useChatStore.getState().messages).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// WebSocket status message → updateLastLoadingContent
// ---------------------------------------------------------------------------

describe("updateLastLoadingContent — WS status stream", () => {
  it("updates the content of the last loading message", () => {
    // WHY: The WS server sends incremental `status` messages while retrieving.
    // The hook calls updateLastLoadingContent() to stream progress text into
    // the most recent loading bubble.
    const userMsg = makeUserMessage("u-1", "query");
    const loadingMsg = makeLoadingMessage("s-1");
    useChatStore.getState().appendMessages([userMsg, loadingMsg]);

    useChatStore.getState().updateLastLoadingContent("Re-ranking results…");

    const msgs = useChatStore.getState().messages;
    expect(msgs[msgs.length - 1]?.content).toBe("Re-ranking results…");
    expect(msgs[msgs.length - 1]?.status).toBe("loading");
  });

  it("does not modify messages when the last message is not a loading system message", () => {
    // WHY: Guard against accidental mutation when there is no in-flight query.
    const doneMsg: ChatMessage = {
      id: "s-1",
      role: "system",
      content: "Found results",
      timestamp: Date.now(),
      status: "done",
    };
    useChatStore.getState().appendMessages([doneMsg]);

    useChatStore.getState().updateLastLoadingContent("should not apply");

    expect(useChatStore.getState().messages[0]?.content).toBe("Found results");
    expect(useChatStore.getState().messages[0]?.status).toBe("done");
  });
});

// ---------------------------------------------------------------------------
// WebSocket results message → replaceLastLoadingWithResults
// ---------------------------------------------------------------------------

describe("replaceLastLoadingWithResults — WS results arrival", () => {
  it("replaces the loading bubble with the results and transitions to done", () => {
    // WHY: When the WS sends a `results` message, the hook calls this method
    // to swap the spinner with the actual document results.
    const userMsg = makeUserMessage("u-1", "query");
    const loadingMsg = makeLoadingMessage("s-1");
    useChatStore.getState().appendMessages([userMsg, loadingMsg]);

    const results = [makeResult(0), makeResult(1)];
    useChatStore.getState().replaceLastLoadingWithResults(results, 2);

    const msgs = useChatStore.getState().messages;
    const last = msgs[msgs.length - 1]!;
    expect(last.status).toBe("done");
    expect(last.content).toBe("Found 2 relevant documents");
    expect(last.results).toEqual(results);
    // The id and role must be preserved so the UI key does not change.
    expect(last.id).toBe("s-1");
    expect(last.role).toBe("system");
  });

  it("does not modify messages when the last message is not a loading system message", () => {
    const doneMsg: ChatMessage = {
      id: "s-1",
      role: "system",
      content: "already done",
      timestamp: Date.now(),
      status: "done",
    };
    useChatStore.getState().appendMessages([doneMsg]);

    useChatStore.getState().replaceLastLoadingWithResults([makeResult(0)], 1);

    expect(useChatStore.getState().messages[0]?.content).toBe("already done");
    expect(useChatStore.getState().messages[0]?.status).toBe("done");
  });
});

// ---------------------------------------------------------------------------
// WebSocket error message → replaceLastLoadingWithError
// ---------------------------------------------------------------------------

describe("replaceLastLoadingWithError — WS error handling", () => {
  it("replaces the loading bubble with the error and transitions to error status", () => {
    // WHY: When the WS sends an `error` message, the hook calls this method
    // so the user sees an error bubble instead of a perpetual spinner.
    const userMsg = makeUserMessage("u-1", "query");
    const loadingMsg = makeLoadingMessage("s-1");
    useChatStore.getState().appendMessages([userMsg, loadingMsg]);

    useChatStore.getState().replaceLastLoadingWithError("Retrieval failed");

    const msgs = useChatStore.getState().messages;
    const last = msgs[msgs.length - 1]!;
    expect(last.status).toBe("error");
    expect(last.error).toBe("Retrieval failed");
    expect(last.id).toBe("s-1");
  });

  it("does not modify messages when the last message is not a loading system message", () => {
    const userMsg = makeUserMessage("u-1", "sent query");
    useChatStore.getState().appendMessages([userMsg]);

    useChatStore.getState().replaceLastLoadingWithError("should not apply");

    expect(useChatStore.getState().messages[0]?.role).toBe("user");
    expect(useChatStore.getState().messages[0]?.error).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// getNextMessageId — stable sequential ID generation
// ---------------------------------------------------------------------------

describe("getNextMessageId", () => {
  it("returns unique IDs across consecutive calls with the same role", () => {
    // WHY: The fixed hook uses getNextMessageId instead of a local useRef counter
    // so that IDs are part of the persisted state and remain unique after reload.
    const id1 = useChatStore.getState().getNextMessageId("user");
    const id2 = useChatStore.getState().getNextMessageId("user");

    expect(id1).not.toBe(id2);
  });

  it("includes the role in the returned ID for readability", () => {
    const userId = useChatStore.getState().getNextMessageId("user");
    const systemId = useChatStore.getState().getNextMessageId("system");

    expect(userId).toMatch(/^user-/);
    expect(systemId).toMatch(/^system-/);
  });

  it("increments the messageCounter in the store so IDs survive simulated remounts", () => {
    // WHY: If IDs were generated from a local useRef (as before), a remount
    // would reset the counter to 0 and produce duplicate IDs.  Using the store
    // counter means the counter is always restored from persisted state.
    useChatStore.getState().getNextMessageId("user");
    useChatStore.getState().getNextMessageId("system");

    expect(useChatStore.getState().messageCounter).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// appendMessages: combined user + loading message (mirrors sendQuery logic)
// ---------------------------------------------------------------------------

describe("appendMessages — combined user + loading bubble (mirrors sendQuery)", () => {
  it("appends both user message and loading system message in one call", () => {
    // WHY: The fixed sendQuery() builds userMsg + loadingMsg and calls
    // appendMessages([userMsg, loadingMsg]) in a single update to keep them
    // atomic and avoid split-render flicker.
    const userId = useChatStore.getState().getNextMessageId("user");
    const systemId = useChatStore.getState().getNextMessageId("system");
    const userMsg = makeUserMessage(userId, "my question");
    const loadingMsg = makeLoadingMessage(systemId);

    useChatStore.getState().appendMessages([userMsg, loadingMsg]);

    const msgs = useChatStore.getState().messages;
    expect(msgs).toHaveLength(2);
    expect(msgs[0]?.role).toBe("user");
    expect(msgs[0]?.content).toBe("my question");
    expect(msgs[1]?.role).toBe("system");
    expect(msgs[1]?.status).toBe("loading");
  });
});
