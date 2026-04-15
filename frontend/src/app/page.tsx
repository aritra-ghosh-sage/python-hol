"use client";

import { useState } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { MainPanel } from "@/components/layout/MainPanel";
import { QueryPanel } from "@/components/chat/QueryPanel";
import { AddDataPanel } from "@/components/data/AddDataPanel";
import { SettingsPanel } from "@/components/settings/SettingsPanel";

type ActivePanel = "query" | "data" | "settings";

export default function Home() {
  const [activePanel, setActivePanel] = useState<ActivePanel>("query");

  const renderPanel = () => {
    switch (activePanel) {
      case "query":
        return <QueryPanel />;
      case "data":
        return <AddDataPanel />;
      case "settings":
        return <SettingsPanel />;
      default:
        return <QueryPanel />;
    }
  };

  return (
    <div className="flex h-screen w-full bg-gray-900">
      <Sidebar activePanel={activePanel} onPanelChange={setActivePanel} />
      <MainPanel>{renderPanel()}</MainPanel>
    </div>
  );
}
