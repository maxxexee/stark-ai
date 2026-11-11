import { errorCopy } from "@stark/api/errors";
import { useResetDemo } from "@stark/api/mutations";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@stark/ui/components/alert-dialog";
import { Button } from "@stark/ui/components/button";
import { FieldError } from "@stark/ui/components/field";
import { Spinner } from "@stark/ui/components/spinner";
import { useState } from "react";

export function ResetDemoDialog() {
  const reset = useResetDemo();
  const [open, setOpen] = useState(false);
  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger render={<Button variant="secondary" />}>Reset</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Reset the demo?</AlertDialogTitle>
          <AlertDialogDescription>
            The seeded bills, balance and history come back. Bills you added are removed.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {reset.error ? <FieldError className="text-sm">{errorCopy(reset.error)}</FieldError> : null}
        <AlertDialogFooter>
          <AlertDialogCancel variant="secondary">Keep my data</AlertDialogCancel>
          <Button
            disabled={reset.isPending}
            onClick={() => reset.mutate(undefined, { onSuccess: () => setOpen(false) })}
          >
            {reset.isPending ? <Spinner /> : null}
            Yes, reset
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
