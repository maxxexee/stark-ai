import { useSetPaused } from "@stark/api/mutations";
import { stateQuery } from "@stark/api/queries";
import { Card } from "@stark/ui/components/card";
import { SwitchRow } from "@stark/ui/components/switch-row";
import { useSuspenseQuery } from "@tanstack/react-query";
import { FormError } from "@/components/auth/form-error";

export function PauseCard() {
  const { data: state } = useSuspenseQuery(stateQuery());
  const setPaused = useSetPaused();

  const handleAllowPayments = (allowed: boolean) => setPaused.mutate(!allowed);

  return (
    <Card className="gap-3">
      <SwitchRow
        checked={!state.paused}
        onChange={handleAllowPayments}
        title={state.paused ? "Stark is paused" : "Stark can pay your bills"}
        subtitle={
          state.paused
            ? "Nothing will be paid until you turn this back on."
            : "Turn this off to stop every payment at once."
        }
      />
      <p className="m-0 text-sm text-fg-2">
        Pausing stops payments from the app, Telegram and the wall phone. Stark still answers
        questions. In Telegram, send /pause or /resume.
      </p>
      <FormError message={setPaused.isError ? "That didn't save. Try again." : null} />
    </Card>
  );
}
