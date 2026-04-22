"use client";

// WHY: useEffect, useRef, useCallback manage WebSocket lifecycle.
// useState is used only for transient connection status (not persisted).
// Chat messages are now stored in useChatStore (Zustand + localStorage) so
// they survive component unmounts that happen when the user switches tabs.
import { useEffect, useState, useRef, useCallback } from "react";
import { getWSClient } from "@/lib/ws";
import { WsIncomingMessage } from "@/lib/types";
import { useChatStore } from "@/stores/chatStore";

export function useChat() {
  const wsClient = useRef(getWSClient());

  // WHY: messages come from the persistent Zustand store instead of local
  // useState.  When the user navigates to a different panel and back, the
  // QueryPanel unmounts and remounts.  A local useState would reset to []
  // on every remount, which was the bug reported in issue #3.
  // The store reads from localStorage on the first render, so existing
  // history appears immediately without a flash of empty content.
  const {
    messages,
    appendMessages,
    updateLastLoadingContent,
    replaceLastLoadingWithResults,
    replaceLastLoadingWithError,
    getNextMessageId,
    clearHistory,
  } = useChatStore();

  // WHY: Connection status is intentionally kept in local useState rather than
  // the store.  It is a transient runtime property (derived from the WebSocket
  // singleton) and does not need to survive a remount or page reload.
  const [isConnected, setIsConnected] = useState(false);
  const [connectionState, setConnectionState] = useState<
    "connecting" | "connected" | "disconnected" | "error"
  >("disconnected");

  // Sync connection state from the singleton on mount so the status bar shows
  // the correct value even if the WS connected before this component mounted.
  useEffect(() => {
    setIsConnected(wsClient.current.isConnected());
    setConnectionState(wsClient.current.getConnectionState());
  }, []);

  // WHY: handleWsMessage is wrapped in useCallback so its reference is stable
  // across renders.  This prevents the WebSocket subscription useEffect below
  // from re-subscribing on every render.
  const handleWsMessage = useCallback((msg: WsIncomingMessage) => {
    if (msg.type === "status") {
      // Stream progress text into the last in-flight loading bubble.
      updateLastLoadingContent(msg.message);
    } else if (msg.type === "results") {
      // Replace the loading bubble with the final document results.
      replaceLastLoadingWithResults(msg.results, msg.total_results);
    } else if (msg.type === "error") {
      // Replace the loading bubble with an error bubble.
      replaceLastLoadingWithError(msg.message);
    }
  }, [updateLastLoadingContent, replaceLastLoadingWithResults, replaceLastLoadingWithError]);

  // Initialize WebSocket on component mount.
  useEffect(() => {
    const client = wsClient.current;
    if (process.env.NODE_ENV !== "production") {
      console.log("[useChat] Mounting, client connection state:", client.getConnectionState());
    }

    // Subscribe to status changes BEFORE connecting so we never miss the first
    // "connected" event.
    const unsubscribeStatus = client.onStatusChange((status) => {
      if (process.env.NODE_ENV !== "production") {
        console.log("[useChat] Status changed to:", status);
      }
      setConnectionState(status);
      setIsConnected(status === "connected");
    });

    // Subscribe to messages.
    const unsubscribeMessages = client.onMessage((msg: WsIncomingMessage) => {
      handleWsMessage(msg);
    });

    // Connect to WebSocket AFTER handlers are registered to avoid a race.
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
      // WHY: We intentionally keep the WebSocket connection alive on unmount
      // so that an in-progress query is not interrupted when the user briefly
      // switches panels.  The singleton ws client manages its own lifecycle.
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

      // WHY: IDs are obtained from the store's counter rather than a local
      // useRef so the counter persists across remounts.  If a local ref were
      // used, the counter would reset to 0 every time the component mounts,
      // potentially producing duplicate React keys in the message list.
      const userMsg = {
        id: getNextMessageId("user"),
        role: "user" as const,
        content: query,
        timestamp: Date.now(),
        status: "sent" as const,
      };

      const loadingMsg = {
        id: getNextMessageId("system"),
        role: "system" as const,
        content: "Searching documents...",
        timestamp: Date.now(),
        status: "loading" as const,
      };

      // Append both messages atomically so the UI never shows the user bubble
      // without the loading indicator beside it.
      appendMessages([userMsg, loadingMsg]);

      // Send via WebSocket.
      wsClient.current.sendQuery(query, enableRerank);
    },
    [isConnected, getNextMessageId, appendMessages]
  );

  return {
    messages,
    sendQuery,
    clearHistory,
    isConnected,
    connectionState,
  };
}
