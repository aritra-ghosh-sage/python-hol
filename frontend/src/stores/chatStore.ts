"use client";

import { create } from "zustand";
import { createJSONStorage, persist, type StateStorage } from "zustand/middleware";
import type { ChatMessage, DocumentResult } from "@/lib/types";

export const MAX_CHAT_HISTORY = 200;

interface ChatStoreState {
  messages: ChatMessage[];
  messageCounter: number;
  appendMessages: (newMessages: ChatMessage[]) => void;
  updateLastLoadingContent: (content: string) => void;
  replaceLastLoadingWithResults: (results: DocumentResult[], totalResults: number) => void;
  replaceLastLoadingWithError: (error: string) => void;
  getNextMessageId: (role: "user" | "system") => string;
  clearHistory: () => void;
}

export function capHistory(messages: ChatMessage[]): ChatMessage[] {
  if (messages.length <= MAX_CHAT_HISTORY) {
    return messages;
  }
  return messages.slice(-MAX_CHAT_HISTORY);
}

const fallbackStorage: StateStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
};

function resolveStorage(): StateStorage {
  if (typeof window === "undefined") {
    return fallbackStorage;
  }

  const candidate = window.localStorage;
  if (
    candidate &&
    typeof candidate.getItem === "function" &&
    typeof candidate.setItem === "function" &&
    typeof candidate.removeItem === "function"
  ) {
    return candidate;
  }

  return fallbackStorage;
}

export const useChatStore = create<ChatStoreState>()(
  persist(
    (set, get) => ({
      messages: [],
      messageCounter: 0,
      appendMessages: (newMessages) => {
        set((state) => ({
          messages: capHistory([...state.messages, ...newMessages]),
        }));
      },
      updateLastLoadingContent: (content) => {
        set((state) => {
          const last = state.messages[state.messages.length - 1];
          if (!last || last.role !== "system" || last.status !== "loading") {
            return state;
          }

          const updatedMessages = [
            ...state.messages.slice(0, -1),
            {
              ...last,
              content,
            },
          ];

          return {
            messages: capHistory(updatedMessages),
          };
        });
      },
      replaceLastLoadingWithResults: (results, totalResults) => {
        set((state) => {
          const last = state.messages[state.messages.length - 1];
          if (!last || last.role !== "system" || last.status !== "loading") {
            return state;
          }

          const updatedMessages = [
            ...state.messages.slice(0, -1),
            {
              ...last,
              content: `Found ${totalResults} relevant documents`,
              results,
              status: "done" as const,
            },
          ];

          return {
            messages: capHistory(updatedMessages),
          };
        });
      },
      replaceLastLoadingWithError: (error) => {
        set((state) => {
          const last = state.messages[state.messages.length - 1];
          if (!last || last.role !== "system" || last.status !== "loading") {
            return state;
          }

          const updatedMessages = [
            ...state.messages.slice(0, -1),
            {
              ...last,
              error,
              status: "error" as const,
            },
          ];

          return {
            messages: capHistory(updatedMessages),
          };
        });
      },
      getNextMessageId: (role) => {
        const current = get().messageCounter;
        set({ messageCounter: current + 1 });
        return `${role}-${current}`;
      },
      clearHistory: () => {
        set({ messages: [] });
      },
    }),
    {
      name: "chat-history-v1",
      storage: createJSONStorage(resolveStorage),
      partialize: (state) => ({
        messages: state.messages,
        messageCounter: state.messageCounter,
      }),
    }
  )
);
