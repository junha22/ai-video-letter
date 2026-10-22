const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  // /api/* 요청은 FastAPI로 넘긴다. 같은 주소를 쓰므로 세션 쿠키와 카카오 redirect가 그대로 동작한다
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
