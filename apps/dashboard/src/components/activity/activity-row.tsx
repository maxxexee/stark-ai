import type { Receipt } from "@stark/api/types";
import { listRowClass, RowText } from "@stark/ui/components/list-row";
import { cn } from "@stark/ui/utils/cn";
import { formatActivityTime, formatNaira } from "@stark/utils/format";
import { Link } from "@tanstack/react-router";
import { ActivityRowStatus } from "@/components/activity/activity-row-status";
import { Receipts } from "@/lib/receipts/receipts";

export function ActivityRow({ receipt, selected }: { receipt: Receipt; selected?: boolean }) {
  return (
    <Link
      to="/activity"
      search={(prev) => ({ ...prev, receipt: receipt.id })}
      className={cn(listRowClass, selected && "bg-surface-selected hover:bg-surface-selected")}
    >
      <span className="tabular w-12 flex-none text-sm text-muted-foreground">
        {formatActivityTime(receipt.created_at)}
      </span>
      <RowText
        title={<span className="font-normal">{receipt.bill_label}</span>}
        subtitle={Receipts.subtitle(receipt)}
      />
      <span
        className={cn(
          "tabular text-base font-medium",
          receipt.status === "declined" && "text-muted-foreground line-through",
        )}
      >
        {formatNaira(Receipts.signedAmount(receipt), {
          sign: receipt.type === "deposit",
        })}
      </span>
      <ActivityRowStatus status={Receipts.status(receipt)} />
    </Link>
  );
}
