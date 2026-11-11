import { Card } from "@stark/ui/components/card";
import { Eyebrow } from "@stark/ui/components/eyebrow";

export function TestMoneyNote() {
  return (
    <Card className="gap-1">
      <Eyebrow>Test money</Eyebrow>
      <span className="font-medium">
        There is no way to pay in real money yet, so nothing is charged.
      </span>
      <span className="text-sm text-muted-foreground">
        It shows up in your balance straight away and is marked as test money in your activity.
      </span>
    </Card>
  );
}
