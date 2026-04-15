"use client";

import { useState, useRef, useEffect } from "react";
import { Send } from "lucide-react";
import { IconButton } from "@/components/ui/IconButton";

interface ChatInputProps {
  onSendQuery: (query: string) => void;
  isConnected: boolean;
}

const MAX_WORDS = 100;

export function ChatInput({ onSendQuery, isConnected }: ChatInputProps) {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const wordCount = input.trim().split(/\s+/).filter((w) => w.length > 0).length;
  const isFull = wordCount >= MAX_WORDS;

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = Math.min(
        textareaRef.current.scrollHeight,
        120
      ) + "px";
    }
  }, [input]);

  const handleSend = () => {
    const query = input.trim();
    if (query && isConnected) {
      onSendQuery(query);
      setInput("");
      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    } else if (e.key === "Escape") {
      setInput("");
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    let value = e.target.value;

    // Enforce word limit
    if (isFull && value.length > input.length) {
      return;
    }

    setInput(value);
  };

  return (
    <div className="border-t border-gray-700 bg-gray-800/50 p-6 space-y-3">
      {/* Word count indicator */}
      <div className="flex justify-between items-center text-xs text-gray-400">
        <span>
          {wordCount} / {MAX_WORDS} words
        </span>
        {isFull && (
          <span className="text-yellow-500">Word limit reached</span>
        )}
      </div>

      {/* Input container */}
      <div className="flex gap-3 items-end">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question... (max 100 words, Shift+Enter for new line)"
          disabled={!isConnected}
          className="flex-1 bg-gray-700 text-white placeholder-gray-400 rounded-lg px-4 py-3 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
          rows={1}
          style={{ maxHeight: "120px", minHeight: "44px" }}
        />
        <IconButton
          onClick={handleSend}
          disabled={!input.trim() || !isConnected}
          className="flex-shrink-0 w-11 h-11"
          title="Send (Enter)"
        >
          <Send className="w-5 h-5" />
        </IconButton>
      </div>

      <p className="text-xs text-gray-400">
        Press <kbd className="bg-gray-700 px-2 py-1 rounded">Enter</kbd> to send,{" "}
        <kbd className="bg-gray-700 px-2 py-1 rounded">Shift + Enter</kbd> for new line
      </p>
    </div>
  );
}
