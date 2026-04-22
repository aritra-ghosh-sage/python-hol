import { beforeEach, describe, expect, it } from "vitest";
import { MAX_CHAT_HISTORY, capHistory, useChatStore } from "./chatStore";
import type { ChatMessage } from "../lib/types";

const STORAGE_KEY = "chat-history-v1";

function makeMessage(i: number): ChatMessage {
  return {
    id: `user-${i}`,
    role: "user",
    content: `message-${i}`,
    timestamp: i,
    status: "sent",
  };
}

function makeLoadingMessage(i: number): ChatMessage {
  return {
    id: `system-${i}`,
    role: "system",
    content: "Searching documents...",
    timestamp: i,
    status: "loading",
  };
}

function readPersistedState(): { messages: ChatMessage[]; messageCounter: number } {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return { messages: [], messageCounter: 0 };
  const parsed = JSON.parse(raw);
  return parsed?.state ?? { messages: [], messageCounter: 0 };
}

function writePersistedState(messages: ChatMessage[], messageCounter: number): void {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ state: { messages, messageCounter }, version: 0 })
  );
}

describe("chatStore history cap", () => {
  beforeEach(() => {
    useChatStore.persist.clearStorage();
    useChatStore.setState({ messages: [], messageCounter: 0 });
  });

  it("keeps only the latest 200 messages in capHistory", () => {
    const input = Array.from({ length: 250 }, (_, i) => makeMessage(i));

    const result = capHistory(input);

    expect(result).toHaveLength(MAX_CHAT_HISTORY);
    expect(result[0]?.id).toBe("user-50");
    expect(result[result.length - 1]?.id).toBe("user-249");
  });

  it("keeps only the latest 200 messages when appending to store", () => {
    const messages = Array.from({ length: 250 }, (_, i) => makeMessage(i));

    useChatStore.getState().appendMessages(messages);
    const stored = useChatStore.getState().messages;

    expect(stored).toHaveLength(MAX_CHAT_HISTORY);
    expect(stored[0]?.id).toBe("user-50");
    expect(stored[stored.length - 1]?.id).toBe("user-249");
  });

  it("preserves all messages when count is exactly at the limit (200)", () => {
    const messages = Array.from({ length: MAX_CHAT_HISTORY }, (_, i) => makeMessage(i));

    useChatStore.getState().appendMessages(messages);
    const stored = useChatStore.getState().messages;

    expect(stored).toHaveLength(MAX_CHAT_HISTORY);
    expect(stored[0]?.id).toBe("user-0");
    expect(stored[MAX_CHAT_HISTORY - 1]?.id).toBe(`user-${MAX_CHAT_HISTORY - 1}`);
  });

  it("drops exactly one oldest message when count exceeds the limit by 1 (201)", () => {
    const messages = Array.from({ length: MAX_CHAT_HISTORY + 1 }, (_, i) => makeMessage(i));

    useChatStore.getState().appendMessages(messages);
    const stored = useChatStore.getState().messages;

    expect(stored).toHaveLength(MAX_CHAT_HISTORY);
    expect(stored[0]?.id).toBe("user-1");
    expect(stored[MAX_CHAT_HISTORY - 1]?.id).toBe(`user-${MAX_CHAT_HISTORY}`);
  });
});

describe("chat history persistence to localStorage", () => {
  beforeEach(() => {
    useChatStore.persist.clearStorage();
    useChatStore.setState({ messages: [], messageCounter: 0 });
  });

  it("persists sent messages to localStorage synchronously", () => {
    const msgs = [makeMessage(0), makeMessage(1), makeMessage(2)];
    useChatStore.getState().appendMessages(msgs);

    const persisted = readPersistedState();

    expect(persisted.messages).toHaveLength(3);
    expect(persisted.messages[0]?.id).toBe("user-0");
    expect(persisted.messages[2]?.id).toBe("user-2");
  });

  it("does not persist loading-status messages", () => {
    const sent = makeMessage(0);
    const loading = makeLoadingMessage(1);
    useChatStore.getState().appendMessages([sent, loading]);

    const persisted = readPersistedState();

    expect(persisted.messages).toHaveLength(1);
    expect(persisted.messages[0]?.id).toBe("user-0");
    expect(persisted.messages.some((m) => m.status === "loading")).toBe(false);
  });

  it("persists only the non-loading messages when mix of statuses exist", () => {
    const msgs: ChatMessage[] = [
      makeMessage(0),
      makeLoadingMessage(1),
      makeMessage(2),
      makeLoadingMessage(3),
      makeMessage(4),
    ];
    useChatStore.getState().appendMessages(msgs);

    const persisted = readPersistedState();

    expect(persisted.messages).toHaveLength(3);
    expect(persisted.messages.map((m) => m.id)).toEqual(["user-0", "user-2", "user-4"]);
  });

  it("persists messageCounter so IDs remain unique across sessions", () => {
    useChatStore.getState().getNextMessageId("user");
    useChatStore.getState().getNextMessageId("user");
    useChatStore.getState().getNextMessageId("system");

    const persisted = readPersistedState();

    expect(persisted.messageCounter).toBe(3);
  });

  it("overwrites previous persisted state on each update", () => {
    useChatStore.getState().appendMessages([makeMessage(0)]);
    useChatStore.getState().appendMessages([makeMessage(1)]);

    const persisted = readPersistedState();

    expect(persisted.messages).toHaveLength(2);
    expect(persisted.messages[1]?.id).toBe("user-1");
  });
});

describe("chat history rehydration (simulated route change)", () => {
  beforeEach(() => {
    useChatStore.persist.clearStorage();
    useChatStore.setState({ messages: [], messageCounter: 0 });
  });

  it("restores messages from localStorage after in-memory state is reset", async () => {
    const msgs = [makeMessage(0), makeMessage(1), makeMessage(2)];

    // Reset in-memory state first — setState triggers a persist write, so any
    // direct localStorage write must come AFTER it to avoid being overwritten.
    useChatStore.setState({ messages: [], messageCounter: 0 });
    expect(useChatStore.getState().messages).toHaveLength(0);

    // Write "previous session" data into localStorage after the setState flush
    writePersistedState(msgs, 3);

    // Rehydrate from storage (what happens on component mount)
    await useChatStore.persist.rehydrate();

    expect(useChatStore.getState().messages).toHaveLength(3);
    expect(useChatStore.getState().messages[0]?.id).toBe("user-0");
    expect(useChatStore.getState().messages[2]?.id).toBe("user-2");
  });

  it("restores messageCounter from localStorage so IDs continue from where they left off", async () => {
    // setState first, then write; rehydrate must win
    useChatStore.setState({ messages: [], messageCounter: 0 });
    writePersistedState([], 42);
    await useChatStore.persist.rehydrate();

    expect(useChatStore.getState().messageCounter).toBe(42);
  });

  it("restores up to 200 messages from localStorage", async () => {
    const msgs = Array.from({ length: MAX_CHAT_HISTORY }, (_, i) => makeMessage(i));

    useChatStore.setState({ messages: [], messageCounter: 0 });
    writePersistedState(msgs, MAX_CHAT_HISTORY);
    await useChatStore.persist.rehydrate();

    expect(useChatStore.getState().messages).toHaveLength(MAX_CHAT_HISTORY);
    expect(useChatStore.getState().messages[0]?.id).toBe("user-0");
    expect(useChatStore.getState().messages[MAX_CHAT_HISTORY - 1]?.id).toBe(
      `user-${MAX_CHAT_HISTORY - 1}`
    );
  });

  it("starts with empty history when localStorage has no saved data", async () => {
    // beforeEach already cleared storage; setState writes empty state to storage
    useChatStore.setState({ messages: [], messageCounter: 0 });
    await useChatStore.persist.rehydrate();

    expect(useChatStore.getState().messages).toHaveLength(0);
    expect(useChatStore.getState().messageCounter).toBe(0);
  });

  it("full round-trip: append → reset → rehydrate restores the same messages", async () => {
    const msgs = [makeMessage(10), makeMessage(11), makeMessage(12)];
    useChatStore.getState().appendMessages(msgs);

    // Capture what the store persisted before the reset
    const persistedBeforeReset = readPersistedState();

    // Simulate route change: reset in-memory state (this also overwrites localStorage)
    useChatStore.setState({ messages: [], messageCounter: 0 });

    // Write the captured state back to localStorage AFTER the setState flush
    writePersistedState(persistedBeforeReset.messages, persistedBeforeReset.messageCounter);

    await useChatStore.persist.rehydrate();

    const restored = useChatStore.getState().messages;
    expect(restored).toHaveLength(3);
    expect(restored.map((m) => m.id)).toEqual(["user-10", "user-11", "user-12"]);
  });
});
