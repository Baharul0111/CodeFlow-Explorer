"use client";

/** The browser only ever holds an opaque session token — never the API key itself. */
const TOKEN_KEY = "codeflow-session-token";
const REMEMBER_KEY = "codeflow-session-remember";

function store(remembered: boolean): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return remembered ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

export function saveSessionToken(token: string, remember: boolean): void {
  try {
    store(remember)?.setItem(TOKEN_KEY, token);
    store(!remember)?.removeItem(TOKEN_KEY);
    window.localStorage.setItem(REMEMBER_KEY, remember ? "1" : "0");
  } catch {
    /* private mode: the token simply does not persist */
  }
}

export function getSessionToken(): string | null {
  try {
    return (
      window.sessionStorage.getItem(TOKEN_KEY) ?? window.localStorage.getItem(TOKEN_KEY) ?? null
    );
  } catch {
    return null;
  }
}

export function clearSessionToken(): void {
  try {
    window.sessionStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(REMEMBER_KEY);
  } catch {
    /* nothing to clear */
  }
}
