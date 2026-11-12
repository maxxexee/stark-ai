import { errorCopy } from "@stark/api/errors";
import { useUpdateLimits } from "@stark/api/mutations";
import type { ApprovalWindow, Limits } from "@stark/api/types";
import { Card } from "@stark/ui/components/card";
import { PillTabs } from "@stark/ui/components/pill-tabs";
import { FormError } from "@/components/auth/form-error";
import { Approvals } from "@/lib/approvals/approvals";

export function ApprovalWindowCard({ limits }: { limits: Limits }) {
  const update = useUpdateLimits();

  const handleWindowChange = (value: `${ApprovalWindow}`) =>
    update.mutate({ approval_window_minutes: Number(value) as ApprovalWindow });

  return (
    <Card className="gap-3">
      <span className="font-medium">When Stark asks first</span>
      <p className="m-0 text-sm text-fg-2">
        If you ask for more than your limits allow, Stark sends it here for you to approve instead
        of refusing. It waits this long, then lapses and pays nothing.
      </p>
      <PillTabs
        label="How long a request waits"
        value={`${limits.approval_window_minutes}`}
        tabs={Approvals.WINDOWS.map((w) => ({ value: `${w.value}` as const, label: w.label }))}
        onChange={handleWindowChange}
      />
      <FormError message={update.isError ? errorCopy(update.error) : null} />
    </Card>
  );
}
