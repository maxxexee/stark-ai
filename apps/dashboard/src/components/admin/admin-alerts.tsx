import { Card } from "@stark/ui/components/card";
import { Eyebrow } from "@stark/ui/components/eyebrow";
import { cn } from "@stark/ui/utils/cn";
import { formatDistanceToNow } from "date-fns";
import type { OperatorAlert } from "@/lib/admin/admin-api";

export function AdminAlerts({ alerts }: { alerts: OperatorAlert[] }) {
  const raised = alerts.filter((alert) => alert.cleared_at === null).length;
  return (
    <Card className={cn(raised > 0 && "border-brand-line bg-brand-wash")}>
      <Eyebrow>{raised > 0 ? `Alerts · ${raised} need you` : "Alerts"}</Eyebrow>
      {alerts.length === 0 ? (
        <p className="m-0 text-sm text-muted-foreground">Nothing needs you.</p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {alerts.map((alert) => (
            <li key={alert.kind} className="flex flex-col gap-0.5">
              <span
                className={cn(
                  "text-sm",
                  alert.cleared_at === null ? "text-fg" : "text-muted-foreground",
                )}
              >
                {alert.cleared_at === null ? alert.message : alert.cleared_message}
              </span>
              <span className="text-xs text-muted-foreground">
                {alert.cleared_at === null
                  ? `Raised ${formatDistanceToNow(alert.raised_at)} ago`
                  : `Cleared ${formatDistanceToNow(alert.cleared_at)} ago`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
