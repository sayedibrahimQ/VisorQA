/** @type {import('next').NextConfig} */
const backendUrl = (
  process.env.NEXT_PUBLIC_API_URL ||
  process.env.BACKEND_URL ||
  "http://16.170.168.155:8000"
).replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  env: {
    // Default to same-origin (empty) so production HTTPS pages call /api
    // and /ws through the rewrites below instead of baking an insecure
    // http:// / ws:// backend address into the bundle (mixed content).
    // Explicit env values (e.g. a wss:// endpoint) still win.
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "",
    NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL || "",
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: "/ws/:path*",
        destination: `${backendUrl}/ws/:path*`,
      },
      {
        source: "/health",
        destination: `${backendUrl}/health`,
      },
    ];
  },
};

export default nextConfig;
