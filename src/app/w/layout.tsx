import type { Metadata } from "next";

// 시청 링크는 검색엔진에 노출되면 안 된다
export const metadata: Metadata = {
  title: "영상 편지가 도착했어요",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function WatchLayout({ children }: { children: React.ReactNode }) {
  return children;
}
