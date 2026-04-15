"use client";

interface MainPanelProps {
  children: React.ReactNode;
}

export function MainPanel({ children }: MainPanelProps) {
  return (
    <main className="flex-1 flex flex-col bg-gray-900 overflow-hidden">
      {children}
    </main>
  );
}
