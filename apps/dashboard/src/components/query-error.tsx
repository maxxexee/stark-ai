import { errorCopy } from "@stark/api/errors";
import { Button } from "@stark/ui/components/button";
import { Card } from "@stark/ui/components/card";
import { useQueryErrorResetBoundary } from "@tanstack/react-query";
import { type ErrorComponentProps, useRouter } from "@tanstack/react-router";
import { useEffect } from "react";

export function QueryError({ error }: ErrorComponentProps) {
  const router = useRouter();
  const { reset } = useQueryErrorResetBoundary();
  useEffect(() => reset(), [reset]);

  return (
    <Card className="items-start">
      <span className="text-lg font-semibold">Can’t load this right now</span>
      <p className="m-0 text-sm text-fg-2">{errorCopy(error)}</p>
      <Button variant="secondary" onClick={() => router.invalidate()}>
        Try again
      </Button>
    </Card>
  );
}
