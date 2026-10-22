import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";

const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";

/** @param {string} phase @returns {import('next').NextConfig} */
const nextConfig = (phase) => ({
  // 실행 중인 개발 서버의 CSS/JS를 next build가 덮어쓰지 않도록 분리한다.
  distDir: phase === PHASE_DEVELOPMENT_SERVER ? ".next-dev" : ".next",
  // /api/* 요청은 FastAPI로 넘긴다. 같은 주소를 쓰므로 세션 쿠키와 카카오 redirect가 그대로 동작한다
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
});

export default nextConfig;
