/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: { serverActions: { bodySizeLimit: "5mb" } }, // resume uploads
};
export default nextConfig;
