"use client";

import { MessageCircle, Plus, Settings } from "lucide-react";

interface SidebarProps {
  activePanel: "query" | "data" | "settings";
  onPanelChange: (panel: "query" | "data" | "settings") => void;
}

export function Sidebar({ activePanel, onPanelChange }: SidebarProps) {
  return (
    <aside className="w-64 bg-gray-800 border-r border-gray-700 flex flex-col p-4 gap-6">
      {/* Logo/Title */}
      <div className="flex items-center gap-3 px-3 py-2">
        <div className="w-10 h-10 bg-blue-500 rounded-lg flex items-center justify-center">
          <MessageCircle className="w-6 h-6 text-white" />
        </div>
        <div>
          <h1 className="font-bold text-lg text-white">Hybrid RAG</h1>
          <p className="text-xs text-gray-400">Query Assistant</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-2">
        <button
          onClick={() => onPanelChange("query")}
          className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
            activePanel === "query"
              ? "bg-blue-500/20 text-blue-400 border border-blue-500/50"
              : "text-gray-300 hover:bg-gray-700/50"
          }`}
        >
          <MessageCircle className="w-5 h-5" />
          <span>Query</span>
        </button>

        <button
          onClick={() => onPanelChange("data")}
          className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
            activePanel === "data"
              ? "bg-blue-500/20 text-blue-400 border border-blue-500/50"
              : "text-gray-300 hover:bg-gray-700/50"
          }`}
        >
          <Plus className="w-5 h-5" />
          <span>Add Data</span>
        </button>

        <button
          onClick={() => onPanelChange("settings")}
          className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
            activePanel === "settings"
              ? "bg-blue-500/20 text-blue-400 border border-blue-500/50"
              : "text-gray-300 hover:bg-gray-700/50"
          }`}
        >
          <Settings className="w-5 h-5" />
          <span>Settings</span>
        </button>
      </nav>

      {/* Footer info */}
      <div className="border-t border-gray-700 pt-4 text-xs text-gray-400">
        <p>v1.0.0</p>
      </div>
    </aside>
  );
}
