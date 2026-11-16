"use client";
import { useEffect, useState } from "react";
import { TOPICS } from "./PreviewKit";
export type Screen="home"|"family"|"conversation"|"compose"|"review"|"share"|"prepare"|"settings"|"notifications"|"login"|"watch";
export type Person={id:number;name:string;relation:string;phone:string;callName:string;tone:string;};
export type Letter={id:number;personId:number;title:string;text:string;date:string;};
export type Reply={id:number;personId:number;text:string;date:string;};
export function usePreviewModel(onWithdraw?:()=>void){
 const [screen,setScreen]=useState<Screen>("home");
 const [people,setPeople]=useState<Person[]>([{id:1,name:"엄마",relation:"어머니",phone:"",callName:"지민",tone:"존댓말"},{id:2,name:"아빠",relation:"아버지",phone:"",callName:"지민",tone:"반말"}]);
 const [personId,setPersonId]=useState(1);
 const [message,setMessage]=useState<string>(TOPICS.안부);
 const [speech,setSpeech]=useState("평소처럼");
 const [emotion,setEmotion]=useState("밝게");
 const [title,setTitle]=useState("오늘도, 당신 생각");
 const [consents,setConsents]=useState([false,false,false]);
 const [voiceStatus,setVoiceStatus]=useState<"none"|"recording"|"processing"|"ready"|"failed">("none");
 const [recorded,setRecorded]=useState(0);
 const [young,setYoung]=useState(false);
 const [tuning,setTuning]=useState<"none"|"training"|"applied">("none");
 useEffect(()=>{if(tuning!=="training")return;const t=window.setTimeout(()=>setTuning("applied"),1200);return()=>window.clearTimeout(t);},[tuning]);
 const [photoUrl,setPhotoUrl]=useState("");
 const [prepTab,setPrepTab]=useState("consent");
 const [status,setStatus]=useState<"draft"|"generating"|"ready"|"failed"|"approved">("draft");
 const [letters,setLetters]=useState<Letter[]>([{id:1,personId:1,title:"엄마, 오늘은 뭐 드셨어요?",text:TOPICS.안부,date:"2026-11-11"},{id:2,personId:2,title:"따뜻하게 입고 다니세요",text:TOPICS.건강,date:"2026-11-08"},{id:3,personId:1,title:"문득 생각나서 남긴 편지",text:TOPICS.감사,date:"2026-10-28"}]);
 const [replies,setReplies]=useState<Reply[]>([{id:1,personId:1,text:"목소리 들으니 참 좋다. 너도 밥 잘 챙겨 먹어!",date:"2026-11-11"}]);
 const [date,setDate]=useState("2026-11-11");
 const [month,setMonth]=useState("2026-11");
 const [recordTab,setRecordTab]=useState("chat");
 const [notice,setNotice]=useState("");
 const [reaction,setReaction]=useState("");
 const [read,setRead]=useState(false);
 const [linkVersion,setLinkVersion]=useState(1);
 const [profile,setProfile]=useState("지민");
 const selected=people.find(p=>p.id===personId)||people[0];
 const consentOk=consents.every(Boolean);
 const ready=consentOk&&voiceStatus==="ready"&&!!photoUrl;
 useEffect(()=>{if(voiceStatus!=="processing")return;const timer=window.setTimeout(()=>setVoiceStatus("ready"),1200);return()=>window.clearTimeout(timer);},[voiceStatus]);
 useEffect(()=>{if(status!=="generating")return;const timer=window.setTimeout(()=>setStatus("ready"),1800);return()=>window.clearTimeout(timer);},[status]);
 useEffect(()=>()=>{if(photoUrl.startsWith("blob:"))URL.revokeObjectURL(photoUrl);},[photoUrl]);
 function navigate(next:Screen){setScreen(next);setNotice("");}
 function openPerson(id:number){setPersonId(id);setDate("2026-11-11");setRecordTab("chat");navigate("conversation");}
 function compose(){setStatus("draft");navigate("compose");}
 function generate(){if(!ready){navigate("prepare");return;}setStatus("generating");navigate("review");}
 function approve(){if(status!=="approved")setLetters(rows=>[{id:Date.now(),personId:selected?.id||0,title,text:message,date:"2026-11-11"},...rows]);setStatus("approved");navigate("share");}
 function withdraw(){onWithdraw?.();setConsents([false,false,false]);setVoiceStatus("none");setRecorded(0);setYoung(false);setTuning("none");setPhotoUrl("");setLetters([]);setStatus("draft");setNotice("샘플 동의를 철회하고 이 탭의 목소리·사진·영상 샘플을 초기화했어요. 원본 계정에는 영향이 없어요.");}
 return {young,setYoung,tuning,setTuning,screen,navigate,people,setPeople,personId,setPersonId,selected,message,setMessage,speech,setSpeech,emotion,setEmotion,title,setTitle,consents,setConsents,consentOk,voiceStatus,setVoiceStatus,recorded,setRecorded,photoUrl,setPhotoUrl,prepTab,setPrepTab,status,setStatus,letters,setLetters,replies,setReplies,date,setDate,month,setMonth,recordTab,setRecordTab,notice,setNotice,reaction,setReaction,read,setRead,linkVersion,setLinkVersion,profile,setProfile,ready,openPerson,compose,generate,approve,withdraw};
}
export type PreviewModel=ReturnType<typeof usePreviewModel>;
export function downloadText(filename:string,content:string){const url=URL.createObjectURL(new Blob([content],{type:"text/plain;charset=utf-8"}));const anchor=document.createElement("a");anchor.href=url;anchor.download=filename;anchor.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000);}
