"use client";

import { useState } from "react";
import { TextInput } from "./TextInput";
import { UrlInput } from "./UrlInput";
import { FileUpload } from "./FileUpload";
import { SourceList } from "./SourceList";

export function AddDataPanel() {
  const [activeTab, setActiveTab] = useState<"text" | "url" | "file">("text");
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const handleDataAdded = () => {
    setRefreshTrigger((prev) => prev + 1);
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="border-b border-gray-700 bg-gray-800/50 px-6 py-4">
        <h2 className="text-xl font-bold text-white">Add Custom Data</h2>
        <p className="text-sm text-gray-400 mt-1">
          Expand the knowledge base by adding text, URLs, or files
        </p>
      </div>

      {/* Tab buttons */}
      <div className="flex gap-2 border-b border-gray-700 px-6 py-3 bg-gray-800/30">
        <button
          onClick={() => setActiveTab("text")}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeTab === "text"
              ? "bg-blue-500 text-white"
              : "text-gray-400 hover:text-gray-300"
          }`}
        >
          Text
        </button>
        <button
          onClick={() => setActiveTab("url")}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeTab === "url"
              ? "bg-blue-500 text-white"
              : "text-gray-400 hover:text-gray-300"
          }`}
        >
          URL
        </button>
        <button
          onClick={() => setActiveTab("file")}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeTab === "file"
              ? "bg-blue-500 text-white"
              : "text-gray-400 hover:text-gray-300"
          }`}
        >
          File
        </button>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-6 space-y-6 max-w-2xl">
          {activeTab === "text" && <TextInput onDataAdded={handleDataAdded} />}
          {activeTab === "url" && <UrlInput onDataAdded={handleDataAdded} />}
          {activeTab === "file" && <FileUpload onDataAdded={handleDataAdded} />}

          {/* Sources section */}
          <div className="mt-10 border-t border-gray-700 pt-6">
            <h3 className="text-lg font-semibold text-white mb-4">
              Ingested Sources
            </h3>
            <SourceList refreshTrigger={refreshTrigger} />
          </div>
        </div>
      </div>
    </div>
  );
}
