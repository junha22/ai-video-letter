"use client";
import {useEffect} from "react";
import {ArrowRight,Bell,Check,PenLine,Settings} from "lucide-react";
import {useAlbumCover} from "@/components/album/useAlbumCover";
import {AlbumCoverEditor} from "@/components/album/AlbumCoverEditor";
import {AlbumFrame} from "@/components/album/AlbumFrame";
import {AlbumCover,AlbumClosing} from "@/components/album/AlbumCover";
import {FamilyAlbumCard} from "@/components/album/FamilyAlbumCard";
import {RecipientPhotoEditor} from "@/components/album/RecipientPhotoEditor";
import {FeaturePages} from "./FeaturePages";
import {usePreviewModel} from "./PreviewModel";
import "./preview.css";
export function DevPreview(){
 const cover=useAlbumCover({preview:true});
 const m=usePreviewModel(()=>{void cover.reset();});
 useEffect(()=>{window.scrollTo({top:0,behavior:"instant" as ScrollBehavior});},[m.screen]);
 const write=<button className="album-primary" onClick={m.compose}>오늘의 마음 남기기<ArrowRight size={17}/></button>;
 return <AlbumFrame preview onHome={()=>m.navigate("home")} navigation={<>{[["home","우리의 앨범"],["family","가족 편지함"],["prepare","편지를 위한 준비"]].map(([id,label])=><button key={id} aria-current={m.screen===id?"page":undefined} onClick={()=>m.navigate(id as "home"|"family"|"prepare")}>{label}</button>)}</>} actions={<><button className="album-icon-button" aria-label="알림" onClick={()=>m.navigate("notifications")}><Bell size={18}/>{!m.read&&<i/>}</button><button className="album-icon-button" aria-label="나의 설정" onClick={()=>m.navigate("settings")}><Settings size={18}/></button><button className="album-write" onClick={m.compose}><PenLine size={15}/>새 편지</button></>}>
 {m.screen==="home"?<><AlbumCover coverImage={cover.url} coverEditor={<AlbumCoverEditor cover={cover}/>} owner={m.profile} action={write} description="서툰 한마디도, 가족에게는 가장 반가운 안부예요."/><section aria-labelledby="album-records-title"><div className="album-section-head"><div><span className="album-eyebrow">ONE ALBUM, ONE SPECIAL PERSON</span><h2 id="album-records-title">차곡차곡, 우리 이야기</h2><p className="family-album-intro">가족마다 한 권씩, 함께 쌓아 가는 마음의 앨범.</p></div><button className="album-text-link" onClick={()=>m.navigate("family")}>가족 추가·관리<ArrowRight size={16}/></button></div>{m.people.length?<div className={`family-album-grid ${m.people.length>2?"family-album-grid-many":""}`}>{m.people.map(person=>{const letters=m.letters.filter(l=>l.personId===person.id);const replies=m.replies.filter(r=>r.personId===person.id);const latest=[...letters,...replies].map(row=>row.date).sort().at(-1);return <FamilyAlbumCard key={person.id} album={{id:person.id,name:person.name,relation:person.relation,photoUrl:person.photoUrl,letterCount:letters.length,replyCount:replies.length,latest:latest?.replaceAll("-","."),onOpen:()=>m.openPerson(person.id)}} editor={<RecipientPhotoEditor variant="album-cover" recipientId={person.id} name={person.name} photoUrl={person.photoUrl} preview={{upload:file=>m.setPersonPhoto(person.id,file),reset:()=>m.resetPersonPhoto(person.id)}}/>}/>;})}</div>:<div className="album-empty"><h3>우리 가족의 첫 앨범을 펼쳐 볼까요?</h3><p>가족을 추가하고, 함께 나눈 마음을 모아 보세요.</p><button className="album-primary" onClick={()=>m.navigate("family")}>가족 앨범 만들기<ArrowRight size={16}/></button></div>}</section><AlbumClosing action={<button className="album-text-link" onClick={m.compose}>편지 한 장 쓰기<ArrowRight size={16}/></button>}/></>:<FeaturePages m={m}/>}
 {m.notice&&<div className="new-preview-notice" role="status"><Check size={17}/><span>{m.notice}</span><button aria-label="안내 닫기" onClick={()=>m.setNotice("")}>×</button></div>}
 </AlbumFrame>;
}
