import { Card } from "@stark/ui/components/card";
import { ResetDemoDialog } from "@/components/settings/reset-demo-dialog";

export function ResetDemo() {
  return (
    <Card className="flex-row flex-wrap items-center gap-3">
      <span className="flex flex-[1_1_240px] flex-col gap-0.5">
        <span className="font-medium">Reset the demo</span>
        <span className="text-sm text-muted-foreground">
          Puts the seeded bills, balance and history back. Bills you added are removed.
        </span>
      </span>
      <ResetDemoDialog />
    </Card>
  );
}
