import { type SessionStore, sessionStore } from "@/lib/auth/session-store";
import type { AuthUser, Session } from "@/lib/auth/types";

export class AuthClient {
  private static readonly VERIFIER_PARAM = "neon_auth_session_verifier";
  private static readonly CALLBACK_PATH = "/auth/callback";

  private readonly sessions: SessionStore;

  constructor(sessions: SessionStore) {
    this.sessions = sessions;
  }

  async signUp(input: { email: string; password: string; name?: string }): Promise<Session> {
    const session = await this.post<Session>("/sign-up/email", {
      email: input.email.trim(),
      password: input.password,
      name: input.name?.trim() || input.email.split("@")[0],
    });
    return this.sessions.save(session, "email");
  }

  async signIn(input: { email: string; password: string }): Promise<Session> {
    const session = await this.post<Session>("/sign-in/email", {
      email: input.email.trim(),
      password: input.password,
    });
    return this.sessions.save(session, "email");
  }

  async signInWithGoogle(): Promise<void> {
    const callbackURL = `${window.location.origin}${AuthClient.CALLBACK_PATH}`;
    const data = await this.post<{ url?: string }>("/sign-in/social", {
      provider: "google",
      callbackURL,
      errorCallbackURL: `${callbackURL}?error=1`,
    });
    if (!data.url) {
      throw new Error("Google sign-in did not return an address to go to.");
    }
    window.location.assign(data.url);
  }

  async sessionFromCallback(search: string): Promise<Session | null> {
    const param = AuthClient.VERIFIER_PARAM;
    const verifier = new URLSearchParams(search).get(param);
    if (!verifier) return null;

    const res = await fetch(
      `${this.baseUrl}/get-session?${param}=${encodeURIComponent(verifier)}`,
      { credentials: "include" },
    );
    if (!res.ok) {
      throw new Error(`Could not finish signing in (${res.status}).`);
    }

    const data = (await res.json().catch(() => null)) as {
      session?: { token?: string } | null;
      user?: AuthUser;
    } | null;
    const token = data?.session?.token;
    if (!token || !data?.user) return null;

    return this.sessions.save({ token, user: data.user }, "google");
  }

  private get baseUrl(): string {
    const url = import.meta.env.VITE_NEON_AUTH_URL;
    if (!url) {
      throw new Error("Sign-in is not configured: set VITE_NEON_AUTH_URL (see .env.example).");
    }
    return url.replace(/\/$/, "");
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = (await res.json().catch(() => null)) as (T & { message?: string }) | null;

    if (!res.ok) {
      throw new Error(data?.message ?? `Could not reach the sign-in service (${res.status}).`);
    }
    if (!data) throw new Error("The sign-in service returned nothing.");
    return data;
  }
}

export const authClient = new AuthClient(sessionStore);
