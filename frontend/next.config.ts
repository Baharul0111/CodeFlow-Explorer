import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  // The dev badge sits bottom-left, exactly on top of the graph's own zoom controls.
  // Compile and runtime errors still surface in the terminal and as overlays.
  devIndicators: false,
};

export default nextConfig;
