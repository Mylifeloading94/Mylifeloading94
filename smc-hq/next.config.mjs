/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false, // R3F + SSE: avoid double-mounting the WebGL context in dev
  experimental: {
    serverComponentsExternalPackages: ['@prisma/client'],
    instrumentationHook: true,
  },
  transpilePackages: ['three'],
};
export default nextConfig;
