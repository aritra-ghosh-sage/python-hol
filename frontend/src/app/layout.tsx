import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
// Note 1: ServiceWorkerDecommissioner replaces the removed ServiceWorkerProvider.
// It renders null and performs a one-time cleanup of the legacy PWA service worker
// and its associated caches on the user's first page load after this release.
import { ServiceWorkerDecommissioner } from "@/components/providers/ServiceWorkerDecommissioner";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
});

// Note 2: The metadata object is processed server-side by Next.js and injected
// into <head> during SSR. The fields "manifest", "themeColor", and "appleWebApp"
// were removed because they are PWA-specific and the app no longer ships a
// service worker or web-app manifest.
export const metadata: Metadata = {
  title: "Hybrid RAG - Query Assistant",
  description: "Ask questions, get intelligent answers. Add your own knowledge sources.",
  icons: {
    icon: "/icon-192.png",
    apple: "/icon-192.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable}`}
    >
      <head>
        {/* Note 3: PWA meta tags removed — mobile-web-app-capable,
            apple-mobile-web-app-*, and the manifest link were specific to the
            Progressive Web App feature that has been removed. The two icon
            links below are retained for favicon and iOS bookmark display. */}
        <link rel="icon" href="/icon-192.png" />
        <link rel="apple-touch-icon" href="/icon-192.png" />
      </head>
      <body className="min-h-screen bg-gray-950 text-gray-100">
        {/* Note 4: ServiceWorkerDecommissioner sits alongside {children}, not
            wrapping them, so it has zero effect on the component tree shape.
            It is a headless component that runs once on mount and then does
            nothing on subsequent renders. */}
        <ServiceWorkerDecommissioner />
        {children}
      </body>
    </html>
  );
}
