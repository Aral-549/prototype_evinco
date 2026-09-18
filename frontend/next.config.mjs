/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Proxy API and media through the Next dev server so the browser makes
    // same-origin requests and CORS never enters the picture during a demo.
    const backend = process.env.BACKEND_ORIGIN || "http://localhost:8000";
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/media/:path*", destination: `${backend}/media/:path*` },
    ];
  },
  // Browser-side calls hit this app's own origin; the key is attached here, in the
  // Next process, so it never appears in a bundle or in devtools.
  async headers() {
    return [];
  },
};
export default nextConfig;
