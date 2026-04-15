"use client";

import { useState } from "react";
import { apiClient } from "@/lib/api";
import { DocumentIngestionRequest } from "@/lib/types";

export function UrlInput() {
  const [url, setUrl] = useState("");
  const [label, setLabel] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  const isValidUrl = (str: string) => {
    try {
      new URL(str);
      return true;
    } catch {
      return false;
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim() || !isValidUrl(url)) {
      setMessage({ type: "error", text: "Please enter a valid URL" });
      return;
    }

    setIsLoading(true);
    setMessage(null);

    try {
      const request: DocumentIngestionRequest = {
        source_type: "url",
        content: url,
        source_label: label || url,
      };

      const response = await apiClient.addDocuments(request);
      setMessage({
        type: "success",
        text: `✓ Fetched and added ${response.chunks_created} chunks`,
      });
      setUrl("");
      setLabel("");
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "Failed to fetch URL",
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-300 mb-2">
          URL
        </label>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          disabled={isLoading}
          className="w-full bg-gray-700 text-white placeholder-gray-400 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          placeholder="https://example.com/article"
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
          placeholder="e.g., Blog Post"
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
        disabled={!url.trim() || !isValidUrl(url) || isLoading}
        className="w-full bg-blue-500 hover:bg-blue-600 disabled:bg-gray-600 disabled:opacity-50 text-white font-medium py-2 px-4 rounded-lg transition-colors"
      >
        {isLoading ? "Fetching..." : "Add from URL"}
      </button>
    </form>
  );
}
