import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";

/** @param {string} phase @returns {import('next').NextConfig} */
const nextConfig = (phase) => ({
  // 실행 중인 개발 서버의 CSS/JS를 next build가 덮어쓰지 않도록 분리한다.
  distDir: phase === PHASE_DEVELOPMENT_SERVER ? ".next-dev" : ".next",
  // 배포 이미지(Dockerfile.web)는 .next/standalone의 server.js만 실행한다
  output: "standalone",
  // /api/* 요청은 src/app/api/[...path]/route.ts가 FastAPI(BACKEND_URL, 실행할 때 읽음)로 넘긴다.
  // rewrites는 쓰지 않는다: Azure에서 큰 응답(영상)이 중간에 멈췄고, Next 14 외부 rewrites에 보안 취약점이 있다
});

export default nextConfig;
