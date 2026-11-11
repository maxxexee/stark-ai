import type { Receipt } from "@stark/api/types";
import { Card } from "@stark/ui/components/card";
import { Eyebrow } from "@stark/ui/components/eyebrow";
import { formatNaira, formatShortDate } from "@stark/utils/format";
import { TopUpBar } from "@/components/bills/top-up-bar";

export function TopUpChart({ history }: { history: Receipt[] }) {
  const paid = history
    .filter((r) => r.status === "delivered")
    .slice(0, 12)
    .reverse();
  if (paid.length < 2) return null;
  const max = Math.max(...paid.map((r) => r.amount_ngn));
  const first = paid[0]!;
  const last = paid.at(-1)!;
  return (
    <Card>
      <Eyebrow>Top-ups</Eyebrow>
      <div
        role="img"
        aria-label={`${paid.length} top-ups from ${formatShortDate(first.created_at)} to ${formatShortDate(last.created_at)}, the latest ${formatNaira(last.amount_ngn)}`}
        className="flex h-40 items-end gap-2"
      >
        {paid.map((r, i) => (
          <TopUpBar key={r.id} receipt={r} max={max} latest={i === paid.length - 1} />
        ))}
      </div>
      <div className="tabular flex justify-between text-xs text-muted-foreground">
        <span>{formatShortDate(first.created_at)}</span>
        <span>{formatShortDate(last.created_at)}</span>
      </div>
    </Card>
  );
}
