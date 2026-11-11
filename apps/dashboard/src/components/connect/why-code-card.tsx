import { Card } from "@stark/ui/components/card";

export function WhyCodeCard() {
  return (
    <Card className="gap-2">
      <span className="font-medium">Why not just trust the chat?</span>
      <p className="m-0 text-sm text-fg-2">
        A bot username is public, so any stranger can message it. The code is what makes a chat{" "}
        <em>you</em>: without one, the bot answers link instructions and nothing else — no balance,
        no bills, no payment.
      </p>
    </Card>
  );
}
