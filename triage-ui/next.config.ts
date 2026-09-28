import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    // The UI calls the API through the rewrite below. Next.js aborts proxied requests after
    // 30s by default, but a full analysis run (embedding + LLM labelling of every cluster)
    // can take longer, so allow up to 10 minutes.
    proxyTimeout: 10 * 60 * 1000,
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${process.env.MOTIF_API_URL || "http://localhost:8000"}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
