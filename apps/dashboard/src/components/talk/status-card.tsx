import { Card } from "@stark/ui/components/card";
import type { ReactNode } from "react";

export function StatusCard({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Card size="sm" className="gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="tabular text-xl font-semibold">{children}</span>
    </Card>
  );
}
