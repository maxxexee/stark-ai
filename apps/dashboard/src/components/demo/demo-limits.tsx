import type { DemoSnapshot } from "@stark/api/types";
import { Card } from "@stark/ui/components/card";
import { formatNaira } from "@stark/utils/format";

export function DemoLimits({ limits }: { limits: DemoSnapshot["limits"] }) {
  return (
    <Card className="gap-2">
      <span className="font-medium">The rules Stark pays by</span>
      <p className="m-0 text-sm text-fg-2">
        At most {formatNaira(limits.monthly_cap_ngn)} a month and{" "}
        {formatNaira(limits.per_payment_cap_ngn)} at once, only to the bills you added. Anything
        over a limit waits for your approval. One tap pauses every payment.
      </p>
    </Card>
  );
}
