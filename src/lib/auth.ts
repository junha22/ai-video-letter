export type AuthConfig = {
  password_login: boolean;
  dev_login: boolean;
  password_min_length: number;
  password_max_length: number | null;
};

export type AuthMethod = "password" | "dev" | "kakao";

export type AuthResult = {
  ok: boolean;
  user: {
    id: number;
    name: string;
    email: string | null;
    auth_method: AuthMethod;
    has_password: boolean;
    kakao: boolean;
  };
  next: string;
};

export const PASSWORD_MIN_LENGTH = 4;

/** Server policy counts Unicode characters and preserves meaningful whitespace. */
export function passwordProblem(password: string): string | null {
  const length = Array.from(password).length;
  if (length < PASSWORD_MIN_LENGTH) {
    return `비밀번호는 ${PASSWORD_MIN_LENGTH}자 이상 입력해 주세요.`;
  }
  return null;
}

/** Only return authenticated application routes; onboarding always takes priority. */
export function authDestination(next: string | undefined, requestedNext?: string | null): string {
  const safe = (path: string | null | undefined): path is string => {
    if (!path || path.includes("\\") || /[\u0000-\u001f\u007f]/.test(path)) return false;
    try {
      const origin = "https://local.invalid";
      const parsed = new URL(path, origin);
      const decoded = decodeURIComponent(parsed.pathname);
      return parsed.origin === origin && path.startsWith("/") && !decoded.includes("\\")
        && !decoded.split("/").some((part) => part === "." || part === "..")
        && /^\/(home|letters|conversations|messages|settings|onboarding)(?:\/|$)/.test(decoded);
    } catch { return false; }
  };
  if (next === "/home" && safe(requestedNext)) return requestedNext;
  return safe(next) ? next : "/home";
}
