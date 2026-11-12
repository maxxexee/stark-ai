import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { AuthIntro } from "@/components/auth/auth-intro";
import { AuthScreen } from "@/components/auth/auth-screen";
import { EmailLogInForm } from "@/components/auth/email-log-in-form";
import { LogInOptions } from "@/components/auth/log-in-options";
import { sessionStore } from "@/lib/auth/session-store";
import type { SignInMethod } from "@/lib/auth/types";

export const Route = createFileRoute("/login")({
  head: () => ({ meta: [{ title: "Log in · Stark" }] }),
  component: LogIn,
});

/** The last-used method is read after mount, so the first render matches the server's. */
function LogIn() {
  const [withEmail, setWithEmail] = useState(false);
  const [lastUsed, setLastUsed] = useState<SignInMethod | null>(null);
  useEffect(() => setLastUsed(sessionStore.lastMethod()), []);

  return (
    <AuthScreen>
      <AuthIntro
        eyebrow="Log in"
        title="Welcome back"
        prompt="New here?"
        link={{ to: "/start", label: "Create an account" }}
      />
      {withEmail ? (
        <EmailLogInForm onBack={() => setWithEmail(false)} />
      ) : (
        <LogInOptions lastUsed={lastUsed} onEmail={() => setWithEmail(true)} />
      )}
    </AuthScreen>
  );
}
