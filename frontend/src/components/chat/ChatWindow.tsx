"use client";

import { ChatMessage } from "@/lib/types";
import { MessageBubble } from "./MessageBubble";
import { useEffect, useRef } from "react";

interface ChatWindowProps {
  messages: ChatMessage[];
}

export function ChatWindow({ messages }: ChatWindowProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-gray-600 scrollbar-track-gray-800 px-6 py-6 space-y-4"
    >
      {messages.length === 0 ? (
        <div className="h-full flex flex-col items-center justify-center gap-4">
          <div className="text-center">
            <h2 className="text-2xl font-bold text-gray-300 mb-2">
              Welcome to Hybrid RAG
            </h2>
            <p className="text-gray-400">
              Ask a question to get started. Use the Add Data panel to expand the knowledge base.
            </p>
          </div>
        </div>
      ) : (
        messages.map((msg) => <MessageBubble key={msg.id} message={msg} />)
      )}
    </div>
  );
}
