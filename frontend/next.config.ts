import type { NextConfig } from "next";

// Where the Django API lives, read at build time:
//   Vercel:  NEXT_PUBLIC_API_URL=https://bakimpilot-api.onrender.com
//   Docker:  API_ORIGIN=http://api:8000 (internal service name)
// The browser never calls that URL directly; see the rewrites below (D-037).
const API_ORIGIN = (process.env.NEXT_PUBLIC_API_URL || process.env.API_ORIGIN || "http://localhost:8000").replace(
  /\/+$/,
  "",
);

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  // Small self-contained server bundle for the Docker image.
  output: "standalone",
  // Django URLs end with "/". Keep them as-is instead of Next's default redirect.
  skipTrailingSlashRedirect: true,
  // The browser only ever talks to this origin; Next proxies /api/* to Django.
  // Same origin = the httpOnly refresh cookie just works, and no CORS is needed (D-027).
  // On Vercel this keeps the cookie first-party even though the API is on onrender.com:
  // browsers block third-party cookies, so calling Render directly would log users out (D-037).
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
