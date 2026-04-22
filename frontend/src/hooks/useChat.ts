"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { getWSClient } from "@/lib/ws";
import { WsIncomingMessage } from "@/lib/types";
import { useChatStore } from "@/stores/chatStore";

export function useChat() {
  const wsClient = useRef(getWSClient());
  const [isConnected, setIsConnected] = useState(false);
  const [connectionState, setConnectionState] = useState<
    "connecting" | "connected" | "disconnected" | "error"
  >("disconnected");

  const messages = useChatStore((state) => state.messages);
  const appendMessages = useChatStore((state) => state.appendMessages);
  const updateLastLoadingContent = useChatStore((state) => state.updateLastLoadingContent);
  const replaceLastLoadingWithResults = useChatStore((state) => state.replaceLastLoadingWithResults);
  const replaceLastLoadingWithError = useChatStore((state) => state.replaceLastLoadingWithError);
  const getNextMessageId = useChatStore((state) => state.getNextMessageId);

  // Sync state from singleton on mount
  useEffect(() => {
    setIsConnected(wsClient.current.isConnected());
    setConnectionState(wsClient.current.getConnectionState());
  }, []);

  // Define message handler before useEffect so it can be used in the dependency array
  const handleWsMessage = useCallback((msg: WsIncomingMessage) => {
    if (msg.type === "status") {
      updateLastLoadingContent(msg.message);
    } else if (msg.type === "results") {
      replaceLastLoadingWithResults(msg.results, msg.total_results);
    } else if (msg.type === "error") {
      replaceLastLoadingWithError(msg.message);
    }
  }, [updateLastLoadingContent, replaceLastLoadingWithResults, replaceLastLoadingWithError]);

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
  }, [handleWsMessage]);

  const sendQuery = useCallback(
    (query: string, enableRerank?: boolean) => {
      if (!isConnected) {
        if (process.env.NODE_ENV !== "production") {
          console.warn("WebSocket not connected");
        }
        return;
      }

      appendMessages([
        {
          id: getNextMessageId("user"),
          role: "user",
          content: query,
          timestamp: Date.now(),
          status: "sent",
        },
        {
          id: getNextMessageId("system"),
          role: "system",
          content: "Searching documents...",
          timestamp: Date.now(),
          status: "loading",
        },
      ]);

      // Send via WebSocket
      wsClient.current.sendQuery(query, enableRerank);
    },
    [isConnected, appendMessages, getNextMessageId]
  );

  return {
    messages,
    sendQuery,
    isConnected,
    connectionState,
  };
}
