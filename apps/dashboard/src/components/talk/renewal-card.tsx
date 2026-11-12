import type { DueBill } from "@stark/api/types";
import { Card } from "@stark/ui/components/card";
import { cn } from "@stark/ui/utils/cn";
import { Link } from "@tanstack/react-router";
import { Bills } from "@/lib/bills/bills";
import { Renewals } from "@/lib/renewals/renewals";

/** Links to the pay screen rather than paying on a tap: one spend path, one confirm. */
export function RenewalCard({ due }: { due: DueBill }) {
  return (
    <Link
      to={Bills.isPayable(due) ? "/pay" : "/bills/$billId"}
      search={
        Bills.isPayable(due) ? { bill: due.id, amount: due.price_ngn ?? undefined } : undefined
      }
      params={Bills.isPayable(due) ? undefined : { billId: due.id }}
      className="col-span-2 rounded-card no-underline lg:col-span-1"
    >
      <Card
        size="sm"
        className={cn(
          "h-full gap-0.5 transition-colors hover:border-line-2",
          due.days_until <= 0 && "border-brand-line bg-brand-wash",
        )}
      >
        <span className="text-xs text-muted-foreground">{due.label} renews</span>
        <span
          className={cn(
            "text-xl font-semibold",
            due.days_until <= 0 ? "text-brand-warm" : "text-fg",
          )}
        >
          {Renewals.when(due.days_until)}
        </span>
      </Card>
    </Link>
  );
}
