import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Prevent webpack from bundling native/heavy modules used in API routes
  serverExternalPackages: [
    "@tensorflow/tfjs",
    "@spotify/basic-pitch",
    "fluent-ffmpeg",
  ],
};

export default nextConfig;
