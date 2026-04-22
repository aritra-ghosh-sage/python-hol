/**
 * Tests for the chat history persistence contract.
 *
 * Testing strategy: we test the Zustand store directly rather than the React
 * hook.  This covers every state transition that `useChat` delegates to the
 * store without requiring @testing-library/react.
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
  // Reset store to a clean slate before each test for full isolation.
  useChatStore.persist.clearStorage();
  useChatStore.setState({ messages: [], messageCounter: 0 });
});

// ---------------------------------------------------------------------------
// Persistence: the core regression guard
// ---------------------------------------------------------------------------

describe("chat history persistence across simulated remounts", () => {
  it("retains messages in the store after clearing and re-reading (simulates tab switch)", () => {
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
    const userMsg = makeUserMessage("u-1", "query");
    const loadingMsg = makeLoadingMessage("s-1");
    useChatStore.getState().appendMessages([userMsg, loadingMsg]);

    useChatStore.getState().updateLastLoadingContent("Re-ranking results…");

    const msgs = useChatStore.getState().messages;
    expect(msgs[msgs.length - 1]?.content).toBe("Re-ranking results…");
    expect(msgs[msgs.length - 1]?.status).toBe("loading");
  });

  it("does not modify messages when the last message is not a loading system message", () => {
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
    // id and role must be preserved so the React key does not change.
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
    // WHY: A local useRef counter would reset to 0 on remount, producing
    // duplicate React keys.  The store counter persists across remounts.
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

