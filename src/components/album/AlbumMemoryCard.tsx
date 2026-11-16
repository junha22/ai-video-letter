import Image from "next/image";
import Link from "next/link";
import { ArrowUpRight, MessageCircle, Play } from "lucide-react";

export type AlbumEntry = {
  id: string;
  title: string;
  recipient: string;
  date: string;
  summary: string;
  status: string;
  state?: string;
  reply?: string;
  recipientPhoto?: string | null;
  href?: string;
  onOpen?: () => void;
};

export function AlbumMemoryCard({ entry }: { entry: AlbumEntry }) {
  const content = <>
    <div className={`album-memory-art ${entry.recipientPhoto ? "has-recipient-photo" : ""}`}>
      <Image src={entry.recipientPhoto || "/images/family-together.webp"} alt={entry.recipientPhoto ? `${entry.recipient}의 사진` : "따뜻한 가족 일러스트"} fill unoptimized={!!entry.recipientPhoto} sizes="(min-width:1000px) 370px,90vw" />
      <span className="album-memory-date">{entry.date}</span>
      <span className="album-memory-video-badge"><Play size={11} aria-hidden="true" />영상 편지</span>
      <span className="album-memory-arrow"><ArrowUpRight size={18} /></span>
    </div>
    <div className="album-memory-content"><span className="album-eyebrow">TO. {entry.recipient}</span><h3>{entry.title}</h3><p>{entry.summary}</p><span className="album-entry-status" data-status={entry.state}>{entry.status}</span></div>
  </>;
  return <article className="album-memory">{entry.href ? <Link href={entry.href} className="album-memory-open" aria-label={`${entry.title} 편지 열기`}>{content}</Link> : <button className="album-memory-open" onClick={entry.onOpen} aria-label={`${entry.title} 편지 열기`}>{content}</button>}{entry.reply && <div className="album-memory-reply"><span><MessageCircle size={12} />{entry.recipient}의 한마디</span><p>“{entry.reply}”</p></div>}</article>;
}
