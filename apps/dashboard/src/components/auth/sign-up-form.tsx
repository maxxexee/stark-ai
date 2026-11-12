import { setAuthToken } from "@stark/api/client";
import { Button } from "@stark/ui/components/button";
import { useNavigate } from "@tanstack/react-router";
import { type SubmitEvent, useState } from "react";
import { FormError } from "@/components/auth/form-error";
import { MethodIcon } from "@/components/auth/method-icon";
import { MethodNote } from "@/components/auth/method-note";
import { MethodPicker } from "@/components/auth/method-picker";
import type { Method } from "@/components/auth/methods";
import { type SignUpDetails, SignUpEmailFields } from "@/components/auth/sign-up-email-fields";
import { authClient } from "@/lib/auth/auth-client";

const CTA: Record<Method, string> = {
  email: "Create account",
  google: "Continue with Google",
};

export function SignUpForm() {
  const navigate = useNavigate();
  const [method, setMethod] = useState<Method>("email");
  const [details, setDetails] = useState<SignUpDetails>({
    first: "",
    last: "",
    email: "",
    password: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const handleSignUp = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (method === "google") {
      setError(null);
      setPending(true);
      try {
        await authClient.signInWithGoogle();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not reach Google.");
        setPending(false);
      }
      return;
    }

    setError(null);
    setPending(true);
    try {
      const session = await authClient.signUp({
        email: details.email,
        password: details.password,
        name: `${details.first} ${details.last}`.trim(),
      });
      setAuthToken(session.token);
      await navigate({ to: "/" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the account.");
    } finally {
      setPending(false);
    }
  };

  return (
    <form className="mt-7 flex flex-col" onSubmit={handleSignUp}>
      <MethodPicker label="Sign-up method" value={method} onChange={setMethod} />

      <div className="mt-4 flex min-h-56 flex-col gap-3">
        {method === "email" ? (
          <SignUpEmailFields details={details} onChange={setDetails} />
        ) : (
          <MethodNote method={method} />
        )}
      </div>

      <FormError message={error} className="mt-3" />

      <Button
        type="submit"
        variant="brand"
        size="lg"
        block
        disabled={pending}
        className="mt-5 gap-2"
      >
        <MethodIcon method={method} />
        {pending
          ? method === "google"
            ? "Taking you to Google…"
            : "Creating your account…"
          : CTA[method]}
      </Button>
    </form>
  );
}
