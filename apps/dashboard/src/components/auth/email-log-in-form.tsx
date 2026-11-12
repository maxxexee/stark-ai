import { setAuthToken } from "@stark/api/client";
import { Button } from "@stark/ui/components/button";
import { useNavigate } from "@tanstack/react-router";
import { type SubmitEvent, useState } from "react";
import { Field } from "@/components/auth/field";
import { FormError } from "@/components/auth/form-error";
import { OrDivider } from "@/components/auth/or-divider";
import { PasswordField } from "@/components/auth/password-field";
import { authClient } from "@/lib/auth/auth-client";

export function EmailLogInForm({ onBack }: { onBack: () => void }) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const handleEmailLogIn = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      const session = await authClient.signIn({ email, password });
      setAuthToken(session.token);
      await navigate({ to: "/" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in.");
    } finally {
      setPending(false);
    }
  };

  return (
    <form className="mt-7 flex flex-col gap-3" onSubmit={handleEmailLogIn}>
      <Field
        label="Email"
        type="email"
        autoComplete="email"
        placeholder="tunde@example.com"
        required
        value={email}
        onChange={setEmail}
      />
      <PasswordField
        autoComplete="current-password"
        placeholder="Your password"
        value={password}
        onChange={setPassword}
      />

      <FormError message={error} />

      <Button type="submit" variant="brand" size="lg" block disabled={pending} className="mt-2">
        {pending ? "Signing in…" : "Log in"}
      </Button>

      <OrDivider />

      <Button type="button" variant="secondary" size="lg" block onClick={onBack}>
        Show other options
      </Button>
    </form>
  );
}
