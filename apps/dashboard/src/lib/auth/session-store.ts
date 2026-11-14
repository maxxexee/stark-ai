import type { Session, SignInMethod } from "@/lib/auth/types";

export class SessionStore {
  private static readonly TOKEN_KEY = "stark.session";
  private static readonly METHOD_KEY = "stark.lastMethod";

  token(): string | null {
    try {
      return window.localStorage.getItem(SessionStore.TOKEN_KEY);
    } catch {
      return null;
    }
  }

  lastMethod(): SignInMethod | null {
    try {
      const method = window.localStorage.getItem(SessionStore.METHOD_KEY);
      return method === "email" || method === "google" ? method : null;
    } catch {
      return null;
    }
  }

  save(session: Session, method: SignInMethod): Session {
    try {
      window.localStorage.setItem(SessionStore.TOKEN_KEY, session.token);
      window.localStorage.setItem(SessionStore.METHOD_KEY, method);
    } catch {}
    return session;
  }

  forget(): void {
    try {
      window.localStorage.removeItem(SessionStore.TOKEN_KEY);
    } catch {}
  }
}

export const sessionStore = new SessionStore();
