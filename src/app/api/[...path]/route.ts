// /api/* 요청을 FastAPI(BACKEND_URL)로 넘기는 프록시. 브라우저는 웹 주소 하나만 보므로 세션 쿠키가 그대로 동작한다.
// next.config의 rewrites 대신 쓴다: Azure에서 rewrites 프록시가 큰 응답(영상)을 중간에 멈춰서 6초 영상이 3초만 재생됐고,
// Next 14의 외부 rewrites에는 보안 취약점(CVE-2026-29057)도 있다. fetch로 받은 본문을 그대로 흘려보낸다.
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// 실행할 때 읽는다 (배포: 같은 Container Apps 환경의 api 앱 주소, 개발: dev.mjs가 넣는 http://127.0.0.1:8000)
const backend = () => (process.env.BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

// 연결마다 정해지는 헤더와, fetch가 다시 계산하는 길이·압축 헤더는 넘기지 않는다
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
  "accept-encoding",
]);

async function proxy(req: NextRequest, { params }: { params: { path: string[] } }) {
  const url = `${backend()}/api/${params.path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });
  // 백엔드가 압축하지 않은 그대로 받는다 (fetch가 몰래 풀면 길이·Range가 어긋난다)
  headers.set("accept-encoding", "identity");
  const hasBody = req.method !== "GET" && req.method !== "HEAD";

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: req.method,
      headers,
      body: hasBody ? await req.arrayBuffer() : undefined,
      redirect: "manual", // 카카오 로그인 등 백엔드의 이동 응답을 브라우저에 그대로 넘긴다
      cache: "no-store",
    });
  } catch {
    return Response.json({ detail: "서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요." }, { status: 502 });
  }

  const out = new Headers();
  upstream.headers.forEach((value, key) => {
    const name = key.toLowerCase();
    // 영상 Range 응답은 길이가 있어야 브라우저가 이어 받는다. 쿠키는 여러 줄이라 아래에서 따로 넣는다
    if (name !== "set-cookie" && (!HOP_BY_HOP.has(name) || name === "content-length")) out.append(key, value);
  });
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);
  const empty = req.method === "HEAD" || upstream.status === 204 || upstream.status === 304;
  return new Response(empty ? null : upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE, proxy as HEAD, proxy as OPTIONS };
