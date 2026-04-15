import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  compress: true,
  // PWA will be configured via sw.ts service worker
};

export default nextConfig;
