import { setAuthToken } from "@stark/api/client";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { CallbackBrand } from "@/components/auth/callback-brand";
import { CallbackError } from "@/components/auth/callback-error";
import { CallbackPending } from "@/components/auth/callback-pending";
import { CallbackTitle } from "@/components/auth/callback-title";
import { authClient } from "@/lib/auth/auth-client";

/**
 * Where the browser lands after Google.
 *
 * Neon finishes the OAuth exchange on its own origin and redirects here with a
 * single-use verifier in the query string. This page spends that verifier on
 * `/get-session`, keeps the token the app already knows how to use, and leaves —
 * so the URL holding the verifier is never the one left in the address bar.
 */

export const Route = createFileRoute("/auth/callback")({
  head: () => ({ meta: [{ title: "Signing in · Stark" }] }),
  component: AuthCallback,
});

function AuthCallback() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(true);
  // The verifier is single-use, and Strict Mode mounts effects twice.
  const spent = useRef(false);

  useEffect(() => {
    if (spent.current) return;
    spent.current = true;

    const search = window.location.search;
    if (new URLSearchParams(search).get("error")) {
      setPending(false);
      setError("Google did not finish signing you in. Try again, or use your email.");
      return;
    }

    authClient
      .sessionFromCallback(search)
      .then((session) => {
        if (!session) {
          setError("That sign-in link has expired. Start again and it will work.");
          setPending(false);
          return;
        }
        setAuthToken(session.token);
        // The verifier is spent: take it out of the address bar and the history.
        window.history.replaceState({}, "", window.location.pathname);
        return navigate({ to: "/" });
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not finish signing in."))
      .finally(() => setPending(false));
  }, [navigate]);

  return (
    <div className="grid min-h-dvh w-full place-items-center bg-canvas px-4">
      <div className="w-full max-w-100">
        <CallbackBrand />
        <CallbackTitle error={error} />
        {error ? <CallbackError error={error} /> : <CallbackPending pending={pending} />}
      </div>
    </div>
  );
}
