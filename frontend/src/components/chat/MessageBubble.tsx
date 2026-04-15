"use client";

import { ChatMessage } from "@/lib/types";
import { Shimmer } from "@/components/ui/Shimmer";

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end mb-4">
        <div className="bg-blue-500 text-white rounded-lg px-4 py-3 max-w-md break-words">
          <p className="text-sm">{message.content}</p>
        </div>
      </div>
    );
  }

  // System message
  return (
    <div className="flex justify-start mb-6">
      <div className="bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 max-w-2xl">
        {message.status === "loading" ? (
          <div className="space-y-2">
            <Shimmer />
          </div>
        ) : message.status === "error" ? (
          <div className="space-y-2">
            <p className="text-sm text-gray-400">{message.content}</p>
            <p className="text-xs text-red-400">{message.error}</p>
          </div>
        ) : (
          <>
            <p className="text-sm text-gray-300 mb-3">{message.content}</p>

            {/* Results */}
            {message.results && message.results.length > 0 && (
              <div className="space-y-3 mt-3 border-t border-gray-700 pt-3">
                {message.results.map((result, idx) => (
                  <div
                    key={idx}
                    className="bg-gray-700/50 rounded px-3 py-2 text-xs space-y-1"
                  >
                    {/* Score badge and source */}
                    <div className="flex items-center justify-between gap-2">
                      <a
                        href={result.source}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-400 hover:text-blue-300 truncate font-medium"
                      >
                        {result.source}
                      </a>
                      <span
                        className="bg-blue-500/30 text-blue-300 px-2 py-0.5 rounded text-xs flex-shrink-0 cursor-help"
                        title={`Relevance: ${(result.score * 100).toFixed(0)}%`}
                      >
                        {(result.score * 100).toFixed(0)}%
                      </span>
                    </div>

                    {/* Text preview */}
                    <p className="text-gray-300 line-clamp-2">
                      {result.text}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
