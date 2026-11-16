"use client";
import {useEffect,useState} from "react";
import {ArrowRight,Bell,Check,PenLine,Settings} from "lucide-react";
import {AlbumFrame} from "@/components/album/AlbumFrame";
import {AlbumCover,AlbumClosing} from "@/components/album/AlbumCover";
import {AlbumMemoryCard} from "@/components/album/AlbumMemoryCard";
import {FeaturePages} from "./FeaturePages";
import {usePreviewModel} from "./PreviewModel";
import "./preview.css";
export function DevPreview(){
 const m=usePreviewModel();const [family,setFamily]=useState(0);const [month,setMonth]=useState("");
 useEffect(()=>{window.scrollTo({top:0,behavior:"instant" as ScrollBehavior});},[m.screen]);
 const months=Array.from(new Set(m.letters.map(l=>l.date.slice(0,7)))).sort().reverse();
 const records=m.letters.filter(l=>(!family||l.personId===family)&&(!month||l.date.startsWith(month)));
 const write=<button className="album-primary" onClick={m.compose}>오늘의 마음 남기기<ArrowRight size={17}/></button>;
 return <AlbumFrame preview onHome={()=>m.navigate("home")} navigation={<>{[["home","우리의 앨범"],["family","가족 편지함"],["prepare","편지를 위한 준비"]].map(([id,label])=><button key={id} aria-current={m.screen===id?"page":undefined} onClick={()=>m.navigate(id as "home"|"family"|"prepare")}>{label}</button>)}</>} actions={<><button className="album-icon-button" aria-label="알림" onClick={()=>m.navigate("notifications")}><Bell size={18}/>{!m.read&&<i/>}</button><button className="album-icon-button" aria-label="나의 설정" onClick={()=>m.navigate("settings")}><Settings size={18}/></button><button className="album-write" onClick={m.compose}><PenLine size={15}/>새 편지</button></>}>
 {m.screen==="home"?<><AlbumCover owner={m.profile} action={write} description="서툰 한마디도, 가족에게는 가장 반가운 안부예요."/><section aria-labelledby="album-records-title"><div className="album-section-head"><div><span className="album-eyebrow">PAGES OF OUR DAYS</span><h2 id="album-records-title">차곡차곡, 우리 이야기</h2></div><button className="album-text-link" onClick={()=>m.navigate("family")}>가족별 대화 보기<ArrowRight size={16}/></button></div><div className="album-filters"><div role="group" aria-label="가족별 편지 필터"><button aria-pressed={family===0} onClick={()=>setFamily(0)}>모든 가족</button>{m.people.map(p=><button key={p.id} aria-pressed={family===p.id} onClick={()=>setFamily(p.id)}>{p.name}</button>)}</div><label>기록을 볼 달<select aria-label="기록을 볼 달" value={month} onChange={e=>setMonth(e.target.value)}><option value="">모든 달</option>{months.map(d=><option key={d} value={d}>{d.replace("-","년 ")}월</option>)}</select></label></div>{records.length?<div className="album-records">{records.map((l,i)=>{const person=m.people.find(p=>p.id===l.personId);const reply=m.replies.find(r=>r.personId===l.personId&&r.date===l.date);return <AlbumMemoryCard key={l.id} entry={{id:String(l.id),title:l.title,recipient:person?.name||"가족",date:l.date.replaceAll("-","."),summary:l.text,status:reply?"가족의 답글이 왔어요":"남겨 둔 마음",reply:reply?.text,art:i%3===0?"son":i%3===1?"daughter":"family",onOpen:()=>{m.setPersonId(l.personId);m.setTitle(l.title);m.setMessage(l.text);m.setStatus("ready");m.navigate("review");}}}/>;})}</div>:<div className="album-empty"><h3>이 페이지는 아직 비어 있어요.</h3><p>새로운 마음을 한 장 남겨 볼까요?</p>{write}</div>}</section><AlbumClosing action={<button className="album-text-link" onClick={m.compose}>편지 한 장 쓰기<ArrowRight size={16}/></button>}/></>:<FeaturePages m={m}/>}
 {m.notice&&<div className="new-preview-notice" role="status"><Check size={17}/><span>{m.notice}</span><button aria-label="안내 닫기" onClick={()=>m.setNotice("")}>×</button></div>}
 </AlbumFrame>;
}
