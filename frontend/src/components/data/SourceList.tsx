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
        setError(null);
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

  const totalDocuments = sources.length;

  return (
    <span className="text-sm text-gray-300">
      {totalDocuments === 0
        ? "No sources ingested yet"
        : `${totalDocuments} ${totalDocuments === 1 ? "document" : "documents"} ingested`}
    </span>
  );
}
