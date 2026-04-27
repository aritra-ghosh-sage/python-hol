/**
 * WebSocket client for real-time chat
 */

import {
  WsIncomingMessage,
  WsOutgoingMessage,
  WsErrorMessage,
} from "./types";

const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws/chat";
const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;

// Debug log for environment configuration
if (typeof window !== "undefined" && process.env.NODE_ENV !== "production") {
  console.log("[WS Config] URL:", WS_URL, "| Env:", process.env.NEXT_PUBLIC_WS_URL);
}

type WsMessageHandler = (message: WsIncomingMessage) => void;
type ConnectionStatusHandler = (
  status: "connecting" | "connected" | "disconnected" | "error"
) => void;

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private messageHandlers: Set<WsMessageHandler> = new Set();
  private statusHandlers: Set<ConnectionStatusHandler> = new Set();
  private connectionState:
    | "connecting"
    | "connected"
    | "disconnected"
    | "error" = "disconnected";
  private retryCount = 0;
  private retryTimeout: NodeJS.Timeout | null = null;

  constructor(url: string = WS_URL) {
    this.url = url;
  }

  getConnectionState() {
    return this.connectionState;
  }

  isConnected(): boolean {
    return this.connectionState === "connected";
  }

  // Debug: Check actual WebSocket state
  debugState() {
    return {
      connectionState: this.connectionState,
      wsReadyState: this.ws?.readyState,
      wsReadyStateText: this.ws
        ? ["CONNECTING", "OPEN", "CLOSING", "CLOSED"][this.ws.readyState]
        : "NO_WS",
      wsUrl: this.ws?.url,
      handlers: this.statusHandlers.size,
    };
  }

  onMessage(handler: WsMessageHandler): () => void {
    this.messageHandlers.add(handler);
    // Return unsubscribe function
    return () => {
      this.messageHandlers.delete(handler);
    };
  }

  onStatusChange(handler: ConnectionStatusHandler): () => void {
    this.statusHandlers.add(handler);
    if (process.env.NODE_ENV !== "production") {
      console.log("[WS] New status handler registered, current state:", this.connectionState);
    }
    // Immediately notify of current state
    handler(this.connectionState);
    return () => {
      this.statusHandlers.delete(handler);
    };
  }

  private notifyStatusChange(
    status: "connecting" | "connected" | "disconnected" | "error"
  ) {
    this.connectionState = status;
    if (process.env.NODE_ENV !== "production") {
      console.log(`[WS] Notifying ${this.statusHandlers.size} handlers of status: ${status}`);
    }
    this.statusHandlers.forEach((handler) => {
      if (process.env.NODE_ENV !== "production") {
        console.log("[WS] Calling status handler");
      }
      handler(status);
    });
  }

  private notifyMessage(message: WsIncomingMessage) {
    this.messageHandlers.forEach((handler) => handler(message));
  }

  connect(): void {
    if (this.connectionState === "connected" || this.connectionState === "connecting") {
      if (process.env.NODE_ENV !== "production") {
        console.log("[WS] Already in state:", this.connectionState);
      }
      return;
    }

    if (process.env.NODE_ENV !== "production") {
      console.log("[WS] Attempting to connect to:", this.url);
    }
    this.retryCount = 0;
    this.notifyStatusChange("connecting");
    if (process.env.NODE_ENV !== "production") {
      console.log("[WS] Status changed to: connecting");
    }

    try {
      this.ws = new WebSocket(this.url);
      console.log("[WS] WebSocket object created");

      this.ws.onopen = () => {
        if (process.env.NODE_ENV !== "production") {
          console.log("[WS] onopen event fired");
        }
        this.retryCount = 0;
        this.notifyStatusChange("connected");
        if (process.env.NODE_ENV !== "production") {
          console.log("[WS] ✓ Connected successfully");
        }
      };

      this.ws.onmessage = (event) => {
        if (process.env.NODE_ENV !== "production") {
          console.log("[WS] Message received:", event.data);
        }
        try {
          const message = JSON.parse(event.data) as WsIncomingMessage;
          this.notifyMessage(message);
        } catch (error) {
          console.error("[WS] Failed to parse message:", error);
        }
      };

      this.ws.onerror = () => {
        // Browser WebSocket API gives an opaque Event on error (no message/code).
        // The real cause is always reported in the subsequent onclose event,
        // which also drives reconnection — so we only log here and let onclose
        // handle the state transition to avoid a spurious error→disconnected flip.
        if (process.env.NODE_ENV !== "production") {
          console.warn(
            `[WS] Connection error (url: ${this.url}) — check that the backend is reachable`
          );
        }
      };

      this.ws.onclose = (event) => {
        if (process.env.NODE_ENV !== "production") {
          console.log(
            `[WS] Closed — code: ${event.code}, reason: "${event.reason || "none"}", clean: ${event.wasClean}`
          );
        }
        this.ws = null;
        if (this.connectionState !== "disconnected") {
          this.notifyStatusChange("disconnected");
          this.attemptReconnect();
        }
      };
    } catch (error) {
      console.error("[WS] Connection failed:", error);
      this.notifyStatusChange("error");
      this.attemptReconnect();
    }
  }

  private attemptReconnect(): void {
    // Use persistent reconnection with capped exponential backoff
    const backoffMs = Math.min(
      INITIAL_BACKOFF_MS * Math.pow(2, this.retryCount),
      MAX_BACKOFF_MS
    );
    this.retryCount++;

    if (process.env.NODE_ENV !== "production") {
      console.log(`[WS] Reconnecting in ${backoffMs}ms (attempt ${this.retryCount})`);
    }

    this.retryTimeout = setTimeout(() => {
      this.connect();
    }, backoffMs);
  }

  sendQuery(query: string, enableRerank?: boolean): void {
    if (!this.ws || this.connectionState !== "connected") {
      if (process.env.NODE_ENV !== "production") {
        console.error("[WS] Not connected");
      }
      const errorMsg: WsErrorMessage = {
        type: "error",
        message: "WebSocket not connected",
      };
      this.notifyMessage(errorMsg);
      return;
    }

    const message: WsOutgoingMessage = {
      query,
      enable_rerank: enableRerank,
    };

    try {
      this.ws.send(JSON.stringify(message));
    } catch (error) {
      console.error("[WS] Failed to send:", error);
      const errorMsg: WsErrorMessage = {
        type: "error",
        message: "Failed to send message",
      };
      this.notifyMessage(errorMsg);
    }
  }

  disconnect(): void {
    if (this.retryTimeout) {
      clearTimeout(this.retryTimeout);
      this.retryTimeout = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    this.notifyStatusChange("disconnected");
    if (process.env.NODE_ENV !== "production") {
      console.log("[WS] Disconnected");
    }
  }
}

// Singleton instance
let wsClientInstance: WebSocketClient | null = null;

export function getWSClient(): WebSocketClient {
  if (!wsClientInstance) {
    wsClientInstance = new WebSocketClient();
  }
  return wsClientInstance;
}

// Expose debug on window for browser console access
if (typeof window !== "undefined" && process.env.NODE_ENV !== "production") {
  (window as unknown as Record<string, unknown>).__wsDebug = () => {
    const client = getWSClient();
    const state = client.debugState();
    console.log("=== WebSocket Debug Info ===");
    console.log("Connection State:", state.connectionState);
    console.log("WS Ready State:", state.wsReadyStateText, `(code: ${state.wsReadyState})`);
    console.log("WS URL:", state.wsUrl || "N/A");
    console.log("Status Handlers:", state.handlers);
    return state;
  };
}
