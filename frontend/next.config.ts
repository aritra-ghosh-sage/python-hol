import type { NextConfig } from "next";

// Note 1: NextConfig is the typed configuration interface for Next.js 16.
// Only options explicitly needed by this project are declared here;
// all others use Next.js built-in defaults.
const nextConfig: NextConfig = {
  reactStrictMode: true,
  compress: true,
};

export default nextConfig;
