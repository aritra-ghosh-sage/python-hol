"use client";

import { useEffect } from "react";
import { Trash2 } from "lucide-react";
import { useChat } from "@/hooks/useChat";
import { getWSClient } from "@/lib/ws";
import { ChatWindow } from "./ChatWindow";
import { ChatInput } from "./ChatInput";

export function QueryPanel() {
  const { messages, sendQuery, clearHistory, isConnected, connectionState } = useChat();

  // Register debug function (dev mode only)
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") {
      const client = getWSClient();
      (window as unknown as Record<string, unknown>).__wsDebug = () => {
        const state = client.debugState();
        console.log("=== WebSocket Debug Info ===");
        console.log("Connection State:", state.connectionState);
        console.log("WS Ready State:", state.wsReadyStateText, `(code: ${state.wsReadyState})`);
        console.log("WS URL:", state.wsUrl || "N/A");
        console.log("Status Handlers:", state.handlers);
        console.log("isConnected:", client.isConnected());
        console.log("===========================");
        return state;
      };
      console.log("[QueryPanel] Debug function __wsDebug() registered. Try: __wsDebug()");
    }
  }, []);

  return (
    <div className="flex flex-col h-full">
      {/* Connection Status Bar */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-gray-700 bg-gray-800/50">
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${
              isConnected ? "bg-green-500" : "bg-red-500"
            }`}
          ></div>
          <span className="text-sm text-gray-400">
            {connectionState === "connecting"
              ? "Connecting..."
              : isConnected
                ? "Connected"
                : "Disconnected"}
          </span>
        </div>

        {/* WHY: clearHistory() clears both in-memory and localStorage state
            to prevent restored messages on reload. Button is disabled when
            history is empty. */}
        <button
          onClick={clearHistory}
          disabled={messages.length === 0}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-400 hover:text-red-400 hover:bg-gray-700/50 rounded-md transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          title="Clear chat history"
        >
          <Trash2 className="w-3.5 h-3.5" />
          <span>Clear history</span>
        </button>
      </div>

      {/* Chat Area */}
      <ChatWindow messages={messages} />

      {/* Input Area */}
      <ChatInput onSendQuery={sendQuery} isConnected={isConnected} />
    </div>
  );
}
