/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "picsum.photos" },
      { protocol: "https", hostname: "fastly.picsum.photos" },
      { protocol: "https", hostname: "m.media-amazon.com" },
      { protocol: "https", hostname: "images-na.ssl-images-amazon.com" },
      // Storefront image proxy on api.hev-shop.com; followed redirect lands
      // on aws-us-east-1.hevlayer.com (the gateway blob route).
      { protocol: "https", hostname: "api.hev-shop.com" },
      { protocol: "https", hostname: "aws-us-east-1.hevlayer.com" },
    ],
  },
};

export default nextConfig;
