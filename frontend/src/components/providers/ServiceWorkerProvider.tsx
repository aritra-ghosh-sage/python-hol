"use client";

import { useEffect } from "react";

export function ServiceWorkerProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  useEffect(() => {
    if (typeof window !== "undefined" && "serviceWorker" in navigator) {
      navigator.serviceWorker
        .register("/sw.js")
        .then((reg) => {
          console.log("[SW] Service Worker registered successfully", reg);
        })
        .catch((error) => {
          console.log("[SW] Service Worker registration failed:", error);
        });
    }
  }, []);

  return <>{children}</>;
}
