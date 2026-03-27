import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Backend proxied via BACKEND_URL env var (set in Vercel project settings)
  // Prevent webpack from bundling native/heavy modules used in API routes
  serverExternalPackages: [
    "@tensorflow/tfjs",
    "@spotify/basic-pitch",
    "fluent-ffmpeg",
  ],
};

export default nextConfig;
