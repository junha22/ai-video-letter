import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DevPreview } from "./DevPreview";

export const metadata: Metadata = {
  title: "온기 | 개발 디자인 프리뷰 · 샘플 데이터",
  robots: { index: false, follow: false },
};

// 서버에서 요청마다 검사한다. 프로덕션 빌드에 프리뷰 HTML을 미리 생성하지 않는다.
export const dynamic = "force-dynamic";

export default function DevPreviewPage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <DevPreview />;
}
