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
        className="flex"
      >
        {paid.map((r, i) => {
          const date = formatShortDate(r.created_at);
          const newDay = i === 0 || date !== formatShortDate(paid[i - 1]!.created_at);
          return (
            <TopUpBar
              key={r.id}
              receipt={r}
              max={max}
              latest={i === paid.length - 1}
              date={newDay ? date : undefined}
            />
          );
        })}
      </div>
    </Card>
  );
}
