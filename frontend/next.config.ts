import type { NextConfig } from "next";

// Where the Django API lives. In Docker this is the internal service name.
const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  // Small self-contained server bundle for the Docker image.
  output: "standalone",
  // Django URLs end with "/". Keep them as-is instead of Next's default redirect.
  skipTrailingSlashRedirect: true,
  // The browser only ever talks to this origin; Next proxies /api/* to Django.
  // Same origin = the httpOnly refresh cookie just works, and no CORS is needed (D-027).
  async rewrites() {
    return [
      { source: "/api/:path*/", destination: `${API_ORIGIN}/api/:path*/` },
      { source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` },
    ];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
