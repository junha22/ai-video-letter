// 화면이 실행할 때 읽는 공개 설정. NEXT_PUBLIC_ 값은 빌드할 때 화면 코드에 박혀서 배포 환경 변수로 바꿀 수 없으므로,
// 배포마다 다른 값은 여기서 넘긴다 (Azure: infra/params.local.json → 웹 컨테이너 환경 변수)
export const dynamic = "force-dynamic";

export function GET() {
  // 카카오 JavaScript 키는 브라우저에 그대로 보이는 공개용 키다. 카카오 콘솔에 등록한 도메인에서만 동작한다.
  // 로컬 개발은 .env.local의 NEXT_PUBLIC_KAKAO_JS_KEY를 그대로 쓴다
  const kakaoJsKey = process.env.KAKAO_JS_KEY || process.env.NEXT_PUBLIC_KAKAO_JS_KEY || "";
  return Response.json({ kakao_js_key: kakaoJsKey }, { headers: { "Cache-Control": "no-store" } });
}
