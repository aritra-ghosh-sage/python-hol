"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { getWSClient } from "@/lib/ws";
import { ChatMessage, WsIncomingMessage, DocumentResult } from "@/lib/types";

export function useChat() {
  const wsClient = useRef(getWSClient());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isConnected, setIsConnected] = useState(() =>
    wsClient.current.isConnected()
  );
  const [connectionState, setConnectionState] = useState<
    "connecting" | "connected" | "disconnected" | "error"
  >(() => wsClient.current.getConnectionState());
  const messageIdRef = useRef(0);

  // Initialize WebSocket on component mount
  useEffect(() => {
    const client = wsClient.current;
    if (process.env.NODE_ENV !== "production") {
      console.log("[useChat] Mounting, client connection state:", client.getConnectionState());
    }

    // Subscribe to status changes BEFORE connecting
    const unsubscribeStatus = client.onStatusChange((status) => {
      if (process.env.NODE_ENV !== "production") {
        console.log("[useChat] Status changed to:", status);
      }
      setConnectionState(status);
      setIsConnected(status === "connected");
    });

    // Subscribe to messages
    const unsubscribeMessages = client.onMessage((msg: WsIncomingMessage) => {
      handleWsMessage(msg);
    });

    // Connect to WebSocket AFTER handlers are registered
    if (process.env.NODE_ENV !== "production") {
      console.log("[useChat] Calling client.connect()");
    }
    client.connect();

    return () => {
      if (process.env.NODE_ENV !== "production") {
        console.log("[useChat] Unmounting");
      }
      unsubscribeStatus();
      unsubscribeMessages();
      // Don't disconnect on unmount - keep connection alive
    };
  }, []);

  const handleWsMessage = useCallback((msg: WsIncomingMessage) => {
    if (msg.type === "status") {
      // Update loading message
      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1];
        if (lastMsg && lastMsg.role === "system" && lastMsg.status === "loading") {
          return [
            ...prev.slice(0, -1),
            {
              ...lastMsg,
              content: msg.message,
            },
          ];
        }
        return prev;
      });
    } else if (msg.type === "results") {
      // Replace loading message with results
      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1];
        if (lastMsg && lastMsg.role === "system" && lastMsg.status === "loading") {
          return [
            ...prev.slice(0, -1),
            {
              ...lastMsg,
              content: `Found ${msg.total_results} relevant documents`,
              results: msg.results,
              status: "done" as const,
            },
          ];
        }
        return prev;
      });
    } else if (msg.type === "error") {
      // Replace loading message with error
      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1];
        if (lastMsg && lastMsg.role === "system" && lastMsg.status === "loading") {
          return [
            ...prev.slice(0, -1),
            {
              ...lastMsg,
              error: msg.message,
              status: "error" as const,
            },
          ];
        }
        return prev;
      });
    }
  }, []);

  const sendQuery = useCallback(
    (query: string, enableRerank?: boolean) => {
      if (!isConnected) {
        if (process.env.NODE_ENV !== "production") {
          console.warn("WebSocket not connected");
        }
        return;
      }

      // Add user message
      const userMsg: ChatMessage = {
        id: `user-${messageIdRef.current++}`,
        role: "user",
        content: query,
        timestamp: Date.now(),
        status: "sent",
      };

      // Add loading system message
      const loadingMsg: ChatMessage = {
        id: `system-${messageIdRef.current++}`,
        role: "system",
        content: "Searching documents...",
        timestamp: Date.now(),
        status: "loading",
      };

      setMessages((prev) => [...prev, userMsg, loadingMsg]);

      // Send via WebSocket
      wsClient.current.sendQuery(query, enableRerank);
    },
    [isConnected]
  );

  return {
    messages,
    sendQuery,
    isConnected,
    connectionState,
  };
}
