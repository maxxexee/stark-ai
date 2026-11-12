import { errorCopy } from "@stark/api/errors";
import { useUpdateLimits } from "@stark/api/mutations";
import type { Limits } from "@stark/api/types";
import { AmountField } from "@stark/ui/components/amount-field";
import { Card } from "@stark/ui/components/card";
import { FieldError, FieldGroup } from "@stark/ui/components/field";
import { type SubmitEvent, useState } from "react";
import { LimitsActions } from "@/components/settings/limits-actions";
import { LimitsDescription } from "@/components/settings/limits-description";
import { LimitsSavedNote } from "@/components/settings/limits-saved-note";

export function SpendingLimitsForm({ limits }: { limits: Limits }) {
  const [monthly, setMonthly] = useState(limits.monthly_cap_ngn);
  const [per, setPer] = useState(limits.per_payment_cap_ngn);
  const update = useUpdateLimits();
  const dirty = monthly !== limits.monthly_cap_ngn || per !== limits.per_payment_cap_ngn;
  const invalid = monthly <= 0 || per <= 0 || per > monthly;

  const handleSaveLimits = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    update.mutate({
      monthly_cap_ngn: monthly,
      per_payment_cap_ngn: per,
    });
  };

  const handleMonthlyChange = (value: number) => {
    update.reset();
    setMonthly(value);
  };

  const handlePerPaymentChange = (value: number) => {
    update.reset();
    setPer(value);
  };

  const handleUndo = () => {
    setMonthly(limits.monthly_cap_ngn);
    setPer(limits.per_payment_cap_ngn);
  };

  return (
    <Card>
      <form className="m-0" onSubmit={handleSaveLimits}>
        <FieldGroup>
          <AmountField
            label="Most Stark can spend in a month"
            value={monthly}
            onChange={handleMonthlyChange}
            presets={[20000, 30000, 50000, 100000]}
          />
          <AmountField
            label="Most it can spend at once"
            value={per}
            onChange={handlePerPaymentChange}
            presets={[5000, 10000, 20000]}
            error={
              per > monthly ? "A single payment can’t be more than the monthly limit." : undefined
            }
          />
          <LimitsDescription spent={limits.spent_ngn} />
          {update.error ? (
            <FieldError className="text-sm">{errorCopy(update.error)}</FieldError>
          ) : null}
          {update.isSuccess && !dirty ? <LimitsSavedNote /> : null}
          {dirty ? (
            <LimitsActions
              monthly={monthly}
              per={per}
              invalid={invalid}
              pending={update.isPending}
              onUndo={handleUndo}
            />
          ) : null}
        </FieldGroup>
      </form>
    </Card>
  );
}
