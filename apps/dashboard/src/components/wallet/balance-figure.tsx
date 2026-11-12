import { formatNaira } from "@stark/utils/format";

export function BalanceFigure({ amount, note }: { amount: number; note: string }) {
  return (
    <div className="flex flex-wrap items-baseline gap-2">
      <span className="tabular text-3xl font-semibold tracking-tight">{formatNaira(amount)}</span>
      <span className="text-sm text-muted-foreground">{note}</span>
    </div>
  );
}
