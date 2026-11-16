import Image from "next/image";
import Link from "next/link";
import { ArrowUpRight, BookOpen, MessageCircle, Video } from "lucide-react";
import type { ReactNode } from "react";

export type FamilyAlbumEntry = {
  id: number;
  name: string;
  relation: string;
  photoUrl?: string | null;
  letterCount: number;
  replyCount: number;
  latest?: string | null;
  href?: string;
  onOpen?: () => void;
};

export function FamilyAlbumCard({ album, editor }: { album: FamilyAlbumEntry; editor: ReactNode }) {
  const content = <>
    <div className={`family-album-cover ${album.photoUrl ? "has-custom-cover" : ""}`}>
      <span className="family-album-spine" aria-hidden="true">OUR FAMILY STORY</span>
      <div className="family-album-cover-art"><Image src={album.photoUrl || "/images/family-together.webp"} alt={`${album.name} 앨범 ${album.photoUrl ? "표지 사진" : "기본 일러스트"}`} fill unoptimized={!!album.photoUrl} sizes="(min-width:1100px) 560px, (min-width:650px) 45vw, 90vw" /></div>
      <span className="family-album-cover-label"><BookOpen size={13} aria-hidden="true" />우리의 한 권</span>
    </div>
    <div className="family-album-info"><div className="family-album-title"><h3>{album.name} 앨범</h3><ArrowUpRight size={20} aria-hidden="true" /></div><p className="family-album-relation">{album.relation} · 함께 나눈 다정한 기록</p>
      <div className="family-album-counts"><span><Video size={13} aria-hidden="true" />편지 {album.letterCount}통</span><span><MessageCircle size={13} aria-hidden="true" />답글 {album.replyCount}개</span></div>
      <p className="family-album-latest">{album.latest ? `최근 기록 · ${album.latest}` : "첫 번째 이야기를 기다리고 있어요."}</p><span className="family-album-open-label">앨범 펼쳐보기 <BookOpen size={13} aria-hidden="true" /></span>
    </div>
  </>;
  return <article className="family-album" data-family-id={album.id}>{album.href ? <Link href={album.href} className="family-album-open" aria-label={`${album.name} 앨범 열기`}>{content}</Link> : <button type="button" onClick={album.onOpen} className="family-album-open" aria-label={`${album.name} 앨범 열기`}>{content}</button>}<div className="family-album-editor">{editor}</div></article>;
}
