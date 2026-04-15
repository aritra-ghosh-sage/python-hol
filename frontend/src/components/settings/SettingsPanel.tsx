"use client";

import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { ConfigResponse, ConfigUpdateRequest } from "@/lib/types";
import { Shimmer } from "@/components/ui/Shimmer";

export function SettingsPanel() {
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [health, setHealth] = useState<"healthy" | "unhealthy" | null>(null);

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        setIsLoading(true);
        const [configRes, healthRes] = await Promise.all([
          apiClient.getConfig(),
          apiClient.healthCheck(),
        ]);
        setConfig(configRes);
        setHealth(healthRes.retriever_ready === "yes" ? "healthy" : "unhealthy");
      } catch (err) {
        setMessage({
          type: "error",
          text: "Failed to load settings",
        });
      } finally {
        setIsLoading(false);
      }
    };

    fetchSettings();
  }, []);

  const handleConfigChange = (key: keyof ConfigResponse, value: any) => {
    if (!config) return;

    // Auto-adjust weights if changing one
    if (key === "semantic_weight" && config.semantic_weight + config.keyword_weight !== 1) {
      const newKeywordWeight = Math.max(0, Math.min(1, 1 - value));
      setConfig({
        ...config,
        [key]: value,
        keyword_weight: parseFloat(newKeywordWeight.toFixed(2)),
      });
    } else if (key === "keyword_weight" && config.semantic_weight + config.keyword_weight !== 1) {
      const newSemanticWeight = Math.max(0, Math.min(1, 1 - value));
      setConfig({
        ...config,
        [key]: value,
        semantic_weight: parseFloat(newSemanticWeight.toFixed(2)),
      });
    } else {
      setConfig({
        ...config,
        [key]: value,
      });
    }
  };

  const handleSave = async () => {
    if (!config) return;

    setIsSaving(true);
    setMessage(null);

    try {
      const update: ConfigUpdateRequest = {
        semantic_top_k: config.semantic_top_k,
        keyword_top_k: config.keyword_top_k,
        final_top_k: config.final_top_k,
        semantic_weight: config.semantic_weight,
        keyword_weight: config.keyword_weight,
        enable_rerank: config.enable_rerank,
        pre_rerank_top_k: config.pre_rerank_top_k,
      };

      await apiClient.updateConfig(update);
      setMessage({
        type: "success",
        text: "✓ Settings saved successfully",
      });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "Failed to save settings",
      });
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="p-6">
        <Shimmer />
      </div>
    );
  }

  if (!config) {
    return (
      <div className="p-6 text-red-400">Failed to load settings</div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-gray-700 bg-gray-800/50 px-6 py-4">
        <h2 className="text-xl font-bold text-white">Settings</h2>
        <p className="text-sm text-gray-400 mt-1">
          Configure retrieval behavior and model parameters
        </p>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl space-y-8">
          {/* Health status */}
          <div className="flex items-center gap-3 p-4 bg-gray-800 rounded-lg border border-gray-700">
            <div
              className={`w-3 h-3 rounded-full ${
                health === "healthy" ? "bg-green-500" : "bg-red-500"
              }`}
            ></div>
            <div>
              <p className="text-sm font-medium text-gray-300">Service Status</p>
              <p className="text-xs text-gray-400">
                {health === "healthy" ? "Retriever ready" : "Retriever offline"}
              </p>
            </div>
          </div>

          {/* Search parameters */}
          <div className="space-y-4">
            <h3 className="font-semibold text-white">Search Parameters</h3>

            <div>
              <label className="text-sm text-gray-300 mb-2 block">
                Semantic Top-K: {config.semantic_top_k}
              </label>
              <input
                type="range"
                min="1"
                max="20"
                value={config.semantic_top_k}
                onChange={(e) =>
                  handleConfigChange("semantic_top_k", parseInt(e.target.value))
                }
                className="w-full"
              />
              <p className="text-xs text-gray-400 mt-1">
                Number of results from semantic search
              </p>
            </div>

            <div>
              <label className="text-sm text-gray-300 mb-2 block">
                Keyword Top-K: {config.keyword_top_k}
              </label>
              <input
                type="range"
                min="1"
                max="20"
                value={config.keyword_top_k}
                onChange={(e) =>
                  handleConfigChange("keyword_top_k", parseInt(e.target.value))
                }
                className="w-full"
              />
              <p className="text-xs text-gray-400 mt-1">
                Number of results from keyword search
              </p>
            </div>

            <div>
              <label className="text-sm text-gray-300 mb-2 block">
                Final Top-K: {config.final_top_k}
              </label>
              <input
                type="range"
                min="1"
                max="20"
                value={config.final_top_k}
                onChange={(e) =>
                  handleConfigChange("final_top_k", parseInt(e.target.value))
                }
                className="w-full"
              />
              <p className="text-xs text-gray-400 mt-1">
                Maximum results to return
              </p>
            </div>
          </div>

          {/* Scoring */}
          <div className="space-y-4 border-t border-gray-700 pt-6">
            <h3 className="font-semibold text-white">Score Weighting</h3>

            <div>
              <label className="text-sm text-gray-300 mb-2 block">
                Semantic Weight: {config.semantic_weight.toFixed(2)}
              </label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={config.semantic_weight}
                onChange={(e) =>
                  handleConfigChange(
                    "semantic_weight",
                    parseFloat(e.target.value)
                  )
                }
                className="w-full"
              />
              <p className="text-xs text-gray-400 mt-1">
                Weight for semantic/embedding-based search results
              </p>
            </div>

            <div>
              <label className="text-sm text-gray-300 mb-2 block">
                Keyword Weight: {config.keyword_weight.toFixed(2)}
              </label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={config.keyword_weight}
                onChange={(e) =>
                  handleConfigChange("keyword_weight", parseFloat(e.target.value))
                }
                className="w-full"
              />
              <p className="text-xs text-gray-400 mt-1">
                Weight for keyword-based search results
              </p>
            </div>

            <p className="text-xs text-gray-400">
              Weights auto-adjust to sum to 1.0
            </p>
          </div>

          {/* Reranking */}
          <div className="space-y-4 border-t border-gray-700 pt-6">
            <h3 className="font-semibold text-white">Reranking</h3>

            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={config.enable_rerank}
                onChange={(e) =>
                  handleConfigChange("enable_rerank", e.target.checked)
                }
                className="w-4 h-4 accent-blue-500"
              />
              <span className="text-sm text-gray-300">
                Enable cross-encoder reranking
              </span>
            </label>
            <p className="text-xs text-gray-400">
              Use a cross-encoder model for more accurate result ranking
            </p>

            {config.enable_rerank && (
              <div>
                <label className="text-sm text-gray-300 mb-2 block">
                  Pre-Rerank Top-K: {config.pre_rerank_top_k}
                </label>
                <input
                  type="range"
                  min="10"
                  max="100"
                  step="10"
                  value={config.pre_rerank_top_k}
                  onChange={(e) =>
                    handleConfigChange(
                      "pre_rerank_top_k",
                      parseInt(e.target.value)
                    )
                  }
                  className="w-full"
                />
                <p className="text-xs text-gray-400 mt-1">
                  Number of candidates to rerank before final selection
                </p>
              </div>
            )}
          </div>

          {/* Message */}
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

          {/* Save button */}
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="w-full bg-blue-500 hover:bg-blue-600 disabled:bg-gray-600 disabled:opacity-50 text-white font-medium py-2 px-4 rounded-lg transition-colors"
          >
            {isSaving ? "Saving..." : "Save Settings"}
          </button>
        </div>
      </div>
    </div>
  );
}
