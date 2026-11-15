"use client";

import { useEffect, useLayoutEffect, useRef, useState, type UIEvent } from "react";
import { errorText } from "@/lib/api";
import { kstDate, mergeConversationEvents, shiftDate, type ConversationDay, type ConversationEvent } from "@/lib/conversations";

/** 대화가 있는 날 며칠씩 받는 피드 한 쪽 (사용자 대화방 /feed, 시니어 링크 /watch/{token}/feed 공통) */
export type FeedPage = {
  today: string;
  days: ConversationDay[];
  events: ConversationEvent[];
  start: string | null;
  end: string | null;
  has_older: boolean;
  has_newer: boolean;
};

/** 화면에 이어 붙인 대화 범위(start~end). hasNewer가 false면 가장 최근 대화까지 보고 있어서 새 답글을 자동으로 붙인다 */
export type ChatWindow = { events: ConversationEvent[]; start: string | null; end: string | null; hasOlder: boolean; hasNewer: boolean };
type PendingScroll = { kind: "bottom" } | { kind: "stay" } | { kind: "keep"; height: number; top: number } | { kind: "day"; date: string };

export const eventKey = (event: ConversationEvent) => `${event.type}-${event.id}`;

function windowOf(res: FeedPage, events: ConversationEvent[]): ChatWindow {
  return { events, start: res.start, end: res.end, hasOlder: res.has_older, hasNewer: res.has_newer };
}

/** 같은 날짜끼리 묶는다 (날짜 구분선용) */
export function byDay(events: ConversationEvent[]): [string, ConversationEvent[]][] {
  const groups: [string, ConversationEvent[]][] = [];
  for (const event of events) {
    const last = groups[groups.length - 1];
    if (last && last[0] === event.date) last[1].push(event);
    else groups.push([event.date, [event]]);
  }
  return groups;
}

type Options<F extends FeedPage> = {
  /** 바뀌면 대화를 처음부터 다시 연다 (대화방 id, 링크 토큰) */
  room: string;
  enabled?: boolean;
  /** 스크롤 상자가 화면에 있는지 (사용자 대화방은 포트폴리오 탭에서 상자가 사라진다) */
  active?: boolean;
  /** query: "", "?before=D", "?after=D" */
  fetchFeed: (query: string) => Promise<F>;
  /** 받은 응답마다 (대상자 이름 등 화면별 정보) */
  onPage?: (res: F) => void;
  /** 실패할 때마다 (링크 만료처럼 화면을 바꿔야 하는 오류) */
  onError?: (e: unknown) => void;
  refreshMs: number;
  /** 처음 열 때 찾아갈 날짜 */
  initialFocus?: () => string | undefined;
  /** 맨 위에 닿으면 이전 대화를 저절로 불러온다 (버튼도 그대로 둔다) */
  autoLoadOlder?: boolean;
};

export function useChatFeed<F extends FeedPage>(options: Options<F>) {
  const { room, enabled = true, active = true, refreshMs, autoLoadOlder = false } = options;
  const opts = useRef(options);
  opts.current = options;
  const [chat, setChat] = useState<ChatWindow | null>(null);
  const [days, setDays] = useState<ConversationDay[]>([]);
  const [today, setToday] = useState(kstDate());
  const [focusDate, setFocusDate] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [loadingNewer, setLoadingNewer] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scrollTick, setScrollTick] = useState(0);
  // 맨 아래에서 떨어져 있는지, 그 사이에 새 영상·답글이 왔는지 ('새 소식' 안내용)
  const [awayFromBottom, setAwayFromBottom] = useState(false);
  const [unseen, setUnseen] = useState(false);
  const chatRef = useRef<ChatWindow | null>(null);
  chatRef.current = chat;
  // 다른 범위를 새로 열 때마다 올린다. 그 전에 출발한 응답은 버린다
  const generation = useRef(0);
  const refreshBusy = useRef(false);
  const olderBusy = useRef(false);
  const newerBusy = useRef(false);
  const scroller = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const pendingScroll = useRef<PendingScroll | null>(null);
  // 맨 아래를 보고 있으면 새 답글이 붙거나 영상 크기가 잡혀도 맨 아래에 붙어 있는다
  const atBottom = useRef(true);
  // 지운 항목은 지우기 전에 출발한 새로고침 응답에 섞여 와도 다시 보이지 않게 한다
  const deleted = useRef(new Set<string>());
  const visible = (events: ConversationEvent[]) => events.filter((event) => !deleted.current.has(eventKey(event)));
  const isLive = chat !== null && !chat.hasNewer;

  const setAt = (bottom: boolean) => {
    atBottom.current = bottom;
    setAwayFromBottom(!bottom);
    if (bottom) setUnseen(false);
  };
  const applyMeta = (res: F) => {
    setDays(res.days);
    setToday(res.today);
    opts.current.onPage?.(res);
  };
  const fail = (e: unknown, gen: number) => {
    if (gen !== generation.current) return;
    setError(errorText(e));
    opts.current.onError?.(e);
  };
  const startWindow = () => {
    const gen = ++generation.current;
    olderBusy.current = false;
    newerBusy.current = false;
    setLoading(true);
    setLoadingOlder(false);
    setLoadingNewer(false);
    return gen;
  };

  /** 최근 대화 며칠을 열고 맨 아래(가장 최근)로 간다. focus가 그 안에 있으면 그날로 간다 */
  const openLatest = async (focus?: string) => {
    const gen = startWindow();
    try {
      const res = await opts.current.fetchFeed("");
      if (gen !== generation.current) return;
      applyMeta(res);
      if (focus && (!res.start || focus < res.start)) {
        void jumpTo(focus);
        return;
      }
      const events = visible(res.events);
      const target = focus ? events.find((event) => event.date >= focus)?.date : undefined;
      pendingScroll.current = target ? { kind: "day", date: target } : { kind: "bottom" };
      setFocusDate(focus ?? null);
      setUnseen(false);
      setChat(windowOf(res, events));
      setError(null);
    } catch (e) {
      fail(e, gen);
    } finally {
      if (gen === generation.current) setLoading(false);
    }
  };

  /** 날짜로 찾기: 이미 불러온 범위면 그날로 스크롤하고, 아니면 그날부터 며칠을 새로 연다 */
  const jumpTo = async (date: string) => {
    setFocusDate(date);
    const current = chatRef.current;
    const loaded = current?.start && current.end && current.start <= date && date <= current.end
      ? current.events.find((event) => event.date >= date)?.date : undefined;
    if (loaded) {
      pendingScroll.current = { kind: "day", date: loaded };
      setScrollTick((n) => n + 1);
      return;
    }
    const gen = startWindow();
    try {
      const res = await opts.current.fetchFeed(`?after=${shiftDate(date, -1)}`);
      if (gen !== generation.current) return;
      if (!res.start) {
        // 그날 뒤로 대화가 없으면 최근 대화를 연다
        void openLatest();
        return;
      }
      applyMeta(res);
      pendingScroll.current = { kind: "day", date: res.start };
      setChat(windowOf(res, visible(res.events)));
      setError(null);
    } catch (e) {
      fail(e, gen);
    } finally {
      if (gen === generation.current) setLoading(false);
    }
  };

  /** 위로 올려서 '이전 대화 보기': 지금 범위 앞의 며칠을 붙이고 보던 자리를 유지한다 */
  const loadOlder = async () => {
    const current = chatRef.current;
    if (!current?.hasOlder || !current.start || olderBusy.current) return;
    const gen = generation.current;
    olderBusy.current = true;
    setLoadingOlder(true);
    try {
      const res = await opts.current.fetchFeed(`?before=${current.start}`);
      if (gen !== generation.current) return;
      applyMeta(res);
      const el = scroller.current;
      if (el) pendingScroll.current = { kind: "keep", height: el.scrollHeight, top: el.scrollTop };
      setChat((prev) => prev && {
        ...prev,
        events: visible(mergeConversationEvents(res.events, prev.events)),
        start: res.start ?? prev.start,
        hasOlder: res.has_older,
      });
      setError(null);
    } catch (e) {
      fail(e, gen);
    } finally {
      if (gen === generation.current) {
        olderBusy.current = false;
        setLoadingOlder(false);
      }
    }
  };

  /** 지난 날짜를 보다가 '이후 대화 보기': 지금 범위 뒤의 며칠을 아래에 붙인다 */
  const loadNewer = async () => {
    const current = chatRef.current;
    if (!current?.hasNewer || !current.end || newerBusy.current) return;
    const gen = generation.current;
    newerBusy.current = true;
    setLoadingNewer(true);
    try {
      const res = await opts.current.fetchFeed(`?after=${current.end}`);
      if (gen !== generation.current) return;
      applyMeta(res);
      // 아래에 붙인 대화를 이어 읽도록 보던 자리에 둔다 (맨 아래에 있었어도 끝으로 건너뛰지 않는다)
      pendingScroll.current = { kind: "stay" };
      setChat((prev) => prev && {
        ...prev,
        events: visible(mergeConversationEvents(prev.events, res.events)),
        end: res.end ?? prev.end,
        hasNewer: res.has_newer,
      });
      setError(null);
    } catch (e) {
      fail(e, gen);
    } finally {
      if (gen === generation.current) {
        newerBusy.current = false;
        setLoadingNewer(false);
      }
    }
  };

  /** 주기적으로·창으로 돌아올 때: 최근 며칠을 서버 것으로 맞춘다 (새 답글, 영상 상태, 다른 곳에서 지운 항목) */
  const refresh = async () => {
    if (refreshBusy.current) return;
    const gen = generation.current;
    refreshBusy.current = true;
    setRefreshing(true);
    try {
      const res = await opts.current.fetchFeed("");
      if (gen !== generation.current) return;
      applyMeta(res);
      const before = chatRef.current;
      if (before && !before.hasNewer && !atBottom.current) {
        const seen = new Set(before.events.map(eventKey));
        if (visible(res.events).some((event) => !seen.has(eventKey(event)))) setUnseen(true);
      }
      setChat((prev) => {
        if (!prev || prev.hasNewer) return prev; // 지난 날짜를 보는 중이면 그대로 둔다
        const kept = res.start ? prev.events.filter((event) => event.date < res.start!) : [];
        const start = prev.start && res.start && prev.start < res.start ? prev.start : res.start;
        return {
          events: visible([...kept, ...res.events]),
          start,
          end: res.end,
          hasOlder: start === res.start ? res.has_older : prev.hasOlder,
          hasNewer: false,
        };
      });
      setError(null);
    } catch (e) {
      fail(e, gen);
    } finally {
      refreshBusy.current = false;
      setRefreshing(false);
    }
  };

  /** 방금 보낸 답글처럼 서버가 돌려준 항목을 바로 붙이고 맨 아래로 간다. 지난 날짜를 보고 있었다면 최근 대화를 연다 */
  const addEvents = (events: ConversationEvent[]) => {
    const current = chatRef.current;
    if (!current || current.hasNewer) {
      void openLatest();
      return;
    }
    const dates = events.map((event) => event.date).sort();
    if (!dates.length) return;
    const first = dates[0];
    const last = dates[dates.length - 1];
    pendingScroll.current = { kind: "bottom" };
    setFocusDate(null);
    setChat((prev) => prev && {
      ...prev,
      events: visible(mergeConversationEvents(prev.events, events)),
      start: prev.start && prev.start < first ? prev.start : prev.start ?? first,
      end: prev.end && prev.end > last ? prev.end : last,
    });
  };

  /** 지운 항목을 화면에서 빼고, 늦게 온 응답에도 다시 나오지 않게 한다 */
  const hideEvent = (key: string) => {
    deleted.current.add(key);
    setChat((prev) => prev && { ...prev, events: prev.events.filter((item) => eventKey(item) !== key) });
  };

  const showLatest = () => {
    if (chatRef.current && !chatRef.current.hasNewer) {
      setFocusDate(null);
      pendingScroll.current = { kind: "bottom" };
      setScrollTick((n) => n + 1);
    } else {
      void openLatest();
    }
  };
  const retry = () => { if (chatRef.current) void refresh(); else void openLatest(); };

  const onScroll = (e: UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    setAt(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
    if (autoLoadOlder && el.scrollTop < 60 && el.scrollHeight > el.clientHeight) void loadOlder();
  };

  const actions = useRef({ openLatest, refresh });
  actions.current = { openLatest, refresh };

  useEffect(() => {
    if (!enabled) return;
    setChat(null);
    setFocusDate(null);
    setDays([]);
    setUnseen(false);
    void actions.current.openLatest(opts.current.initialFocus?.());
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void actions.current.refresh(); }, refreshMs);
    const onFocus = () => { void actions.current.refresh(); };
    window.addEventListener("focus", onFocus);
    return () => { generation.current += 1; window.clearInterval(timer); window.removeEventListener("focus", onFocus); };
  }, [enabled, room, refreshMs]);

  // 새로 연 범위·붙인 대화에 맞춰 스크롤한다 (그리기 전에 해서 화면이 튀지 않게)
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el || !active) return;
    const pending = pendingScroll.current;
    pendingScroll.current = null;
    if (pending?.kind === "keep") {
      el.scrollTop = pending.top + (el.scrollHeight - pending.height);
    } else if (pending?.kind === "day" || pending?.kind === "stay") {
      const target = pending.kind === "day" ? el.querySelector<HTMLElement>(`[data-day="${pending.date}"]`) : null;
      if (target) el.scrollTop = Math.max(0, target.offsetTop - 4);
      setAt(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
    } else if (pending?.kind === "bottom" || atBottom.current) {
      el.scrollTop = el.scrollHeight;
      setAt(true);
    }
  }, [chat, active, scrollTick]);

  // 영상 크기가 늦게 잡히거나 대본을 펼쳐도, 맨 아래를 보고 있었다면 맨 아래에 붙어 있는다
  useEffect(() => {
    const el = scroller.current;
    const inner = content.current;
    if (!el || !inner || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => { if (atBottom.current) el.scrollTop = el.scrollHeight; });
    observer.observe(inner);
    return () => observer.disconnect();
  }, [active, enabled]);

  return {
    chat, days, today, focusDate, isLive, loading, refreshing, loadingOlder, loadingNewer, error, setError,
    awayFromBottom, unseen, scroller, content, onScroll,
    openLatest, jumpTo, loadOlder, loadNewer, refresh, addEvents, hideEvent, showLatest, retry,
  };
}
