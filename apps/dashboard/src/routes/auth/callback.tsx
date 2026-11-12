import { setAuthToken } from "@stark/api/client";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { CallbackBrand } from "@/components/auth/callback-brand";
import { CallbackError } from "@/components/auth/callback-error";
import { CallbackPending } from "@/components/auth/callback-pending";
import { CallbackTitle } from "@/components/auth/callback-title";
import { authClient } from "@/lib/auth/auth-client";

/**
 * Spends Neon's single-use OAuth verifier on `/get-session`, then removes it from the address bar
 * and history. A ref guards the exchange because Strict Mode mounts effects twice.
 */

export const Route = createFileRoute("/auth/callback")({
  head: () => ({ meta: [{ title: "Signing in · Stark" }] }),
  component: AuthCallback,
});

function AuthCallback() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(true);
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
