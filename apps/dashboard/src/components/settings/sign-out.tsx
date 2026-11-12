import { api, setAuthToken } from "@stark/api/client";
import { Button } from "@stark/ui/components/button";
import { FieldError } from "@stark/ui/components/field";
import { Spinner } from "@stark/ui/components/spinner";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { sessionStore } from "@/lib/auth/session-store";

/**
 * Logs out on the server before forgetting the local token, which alone would leave a live session
 * behind.
 */
export function SignOut() {
  const navigate = useNavigate();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSignOut = async () => {
    setPending(true);
    setError(null);
    try {
      await api.logout();
    } catch {}
    try {
      sessionStore.forget();
      setAuthToken(null);
      await navigate({ to: "/login" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign out.");
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="secondary" onClick={handleSignOut} disabled={pending} className="self-start">
        {pending ? <Spinner /> : null}
        Log out
      </Button>
      {error ? <FieldError className="text-sm">{error}</FieldError> : null}
    </div>
  );
}
