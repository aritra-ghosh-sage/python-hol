"use client";

import { useState } from "react";
import { apiClient } from "@/lib/api";
import { DocumentIngestionRequest } from "@/lib/types";

export function TextInput() {
  const [text, setText] = useState("");
  const [label, setLabel] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;

    setIsLoading(true);
    setMessage(null);

    try {
      const request: DocumentIngestionRequest = {
        source_type: "text",
        content: text,
        source_label: label || "Text Document",
      };

      const response = await apiClient.addDocuments(request);
      setMessage({
        type: "success",
        text: `✓ Added ${response.chunks_created} chunks from ${response.documents_added} document`,
      });
      setText("");
      setLabel("");
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "Failed to add document",
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-300 mb-2">
          Text Content
        </label>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={isLoading}
          className="w-full bg-gray-700 text-white placeholder-gray-400 rounded-lg px-4 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 h-40 resize-none"
          placeholder="Paste your text here..."
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-300 mb-2">
          Label (optional)
        </label>
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          disabled={isLoading}
          className="w-full bg-gray-700 text-white placeholder-gray-400 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          placeholder="e.g., My FAQ, Documentation"
        />
      </div>

      {message && (
        <div
          className={`p-3 rounded-lg text-sm ${
            message.type === "success"
              ? "bg-green-500/20 text-green-300 border border-green-500/50"
              : "bg-red-500/20 text-red-300 border border-red-500/50"
          }`}
        >
          {message.text}
        </div>
      )}

      <button
        type="submit"
        disabled={!text.trim() || isLoading}
        className="w-full bg-blue-500 hover:bg-blue-600 disabled:bg-gray-600 disabled:opacity-50 text-white font-medium py-2 px-4 rounded-lg transition-colors"
      >
        {isLoading ? "Adding..." : "Add Document"}
      </button>
    </form>
  );
}
