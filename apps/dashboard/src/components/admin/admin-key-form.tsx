import { Button } from "@stark/ui/components/button";
import { Card } from "@stark/ui/components/card";
import { Input } from "@stark/ui/components/input";
import { useState } from "react";
import { FormError } from "@/components/auth/form-error";

export function AdminKeyForm({
  error,
  onSubmit,
}: {
  error: string | null;
  onSubmit: (key: string) => void;
}) {
  const [key, setKey] = useState("");
  return (
    <Card className="mx-auto w-full max-w-sm">
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit(key.trim());
        }}
      >
        <label htmlFor="admin-key" className="text-sm font-medium">
          Admin key
        </label>
        <Input
          id="admin-key"
          type="password"
          autoComplete="off"
          value={key}
          onChange={(event) => setKey(event.target.value)}
          aria-invalid={error ? true : undefined}
        />
        <FormError message={error} />
        <Button type="submit" variant="brand" disabled={!key.trim()}>
          Open
        </Button>
      </form>
    </Card>
  );
}
