/** @type {import('next').NextConfig} */
const nextConfig = {
  // NEXT_PUBLIC_API_URL  – HTTP base for all /api/* calls
  //   Local:      http://localhost:8000
  //   Production: https://<your-railway-app>.railway.app
  //
  // NEXT_PUBLIC_WS_URL   – WebSocket base for /ws/* connections
  //   Local:      ws://localhost:8000
  //   Production: wss://<your-railway-app>.railway.app
  //
  // Vercel: set both in Project → Settings → Environment Variables.

  async rewrites() {
    // Use 127.0.0.1 explicitly — Node.js resolves "localhost" as ::1 (IPv6)
    // on macOS but uvicorn only binds IPv4, causing ECONNREFUSED.
    const backendUrl =
      process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

    return [
      // Proxy /api/* and /ws/* to the Railway backend so the browser never
      // needs to know the backend origin (avoids CORS in production).
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: "/ws/:path*",
        destination: `${backendUrl}/ws/:path*`,
      },
    ];
  },
};

export default nextConfig;
