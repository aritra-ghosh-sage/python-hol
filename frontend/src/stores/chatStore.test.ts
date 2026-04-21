import { beforeEach, describe, expect, it } from "vitest";
import { MAX_CHAT_HISTORY, capHistory, useChatStore } from "./chatStore";
import type { ChatMessage } from "../lib/types";

function makeMessage(i: number): ChatMessage {
  return {
    id: `user-${i}`,
    role: "user",
    content: `message-${i}`,
    timestamp: i,
    status: "sent",
  };
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
});
