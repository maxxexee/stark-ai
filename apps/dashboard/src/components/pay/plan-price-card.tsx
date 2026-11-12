import { formatNaira } from "@stark/utils/format";

// The same tray and panel as the typed amount, read-only: a plan's price is fixed.
export function PlanPriceCard({ amount, provider }: { amount: number; provider: string }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="rounded-card bg-muted p-1">
        <div className="flex flex-col gap-3 rounded-lg bg-card px-4 py-3.5">
          <span className="text-sm text-muted-foreground">Amount</span>
          <span className="tabular flex h-10 items-center text-3xl tracking-tight">
            {formatNaira(amount)}
          </span>
        </div>
      </div>
      <span className="text-sm text-muted-foreground">
        The {provider} plan price. Plans can’t be part-paid.
      </span>
    </div>
  );
}
