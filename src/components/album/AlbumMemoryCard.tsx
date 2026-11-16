import Image from "next/image";
import Link from "next/link";
import { ArrowUpRight, MessageCircle } from "lucide-react";
export type AlbumEntry={id:string;title:string;recipient:string;date:string;summary:string;status:string;state?:string;reply?:string;poster?:string|null;art?:"family"|"son"|"daughter";href?:string;onOpen?:()=>void;};
export function AlbumMemoryCard({entry}:{entry:AlbumEntry}){
 const art=entry.art==="son"?"son-character":entry.art==="daughter"?"daughter-character":"family-together";
 const content=<><div className={`album-memory-art ${entry.poster?"has-poster":""}`}><Image src={entry.poster||`/images/${art}.webp`} alt={entry.poster?`${entry.recipient}께 보낸 영상 편지 미리보기`:""} fill unoptimized={!!entry.poster} sizes="(min-width:1000px) 370px,90vw"/><span className="album-memory-date">{entry.date}</span><span className="album-memory-arrow"><ArrowUpRight size={18}/></span></div><div className="album-memory-content"><span className="album-eyebrow">TO. {entry.recipient}</span><h3>{entry.title}</h3><p>{entry.summary}</p><span className="album-entry-status" data-status={entry.state}>{entry.status}</span></div></>;
 return <article className="album-memory">{entry.href?<Link href={entry.href} className="album-memory-open" aria-label={`${entry.title} 편지 열기`}>{content}</Link>:<button className="album-memory-open" onClick={entry.onOpen} aria-label={`${entry.title} 편지 열기`}>{content}</button>}{entry.reply&&<div className="album-memory-reply"><span><MessageCircle size={12}/>{entry.recipient}의 한마디</span><p>“{entry.reply}”</p></div>}</article>;
}
