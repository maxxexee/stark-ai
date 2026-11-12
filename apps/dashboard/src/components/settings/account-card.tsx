import { Card } from "@stark/ui/components/card";
import { SignOut } from "@/components/settings/sign-out";

export function AccountCard() {
  return (
    <Card className="gap-2">
      <span className="font-medium">Signed in</span>
      <SignOut />
    </Card>
  );
}
