export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

type Options = { method?: string; json?: unknown; form?: FormData; signal?: AbortSignal };

/** 같은 주소의 /api/* 로 요청한다 (next.config.mjs에서 FastAPI로 프록시). */
export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  const method = opts.method ?? (opts.json !== undefined || opts.form ? "POST" : "GET");
  const res = await fetch(path, {
    method,
    headers: opts.json !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: opts.json !== undefined ? JSON.stringify(opts.json) : opts.form,
    cache: "no-store",
    signal: opts.signal,
  });
  if (!res.ok) {
    let message = "요청을 처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.";
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail)) message = "입력한 내용을 다시 확인해 주세요.";
    } catch {
      // 본문이 JSON이 아니면 기본 문구를 쓴다
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : "알 수 없는 오류가 생겼어요.";
}
