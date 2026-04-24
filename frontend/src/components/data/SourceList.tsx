"use client";

import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { DocumentSource } from "@/lib/types";
import { Shimmer } from "@/components/ui/Shimmer";

interface SourceListProps {
  refreshTrigger?: number;
}

export function SourceList({ refreshTrigger }: SourceListProps) {
  const [sources, setSources] = useState<DocumentSource[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchSources = async () => {
      try {
        setIsLoading(true);
        const response = await apiClient.getDocumentSources();
        setSources(response.sources);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load sources");
      } finally {
        setIsLoading(false);
      }
    };

    fetchSources();
  }, [refreshTrigger]);

  if (isLoading) {
    return <Shimmer />;
  }

  if (error) {
    return (
      <div className="bg-red-500/20 text-red-300 px-3 py-2 rounded text-sm">
        {error}
      </div>
    );
  }

  if (sources.length === 0) {
    return (
      <div className="text-gray-400 text-sm px-3 py-2">
        No sources added yet. Start by adding text, URL, or files above.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {sources.map((source) => (
        <div
          key={source.source}
          className="flex items-center justify-between bg-gray-800 px-3 py-2 rounded border border-gray-700"
        >
          <span className="text-sm text-gray-300 truncate">
            {source.source}
          </span>
          <span className="text-xs bg-blue-500/30 text-blue-300 px-2 py-1 rounded flex-shrink-0">
            {source.count} chunks
          </span>
        </div>
      ))}
    </div>
  );
}
