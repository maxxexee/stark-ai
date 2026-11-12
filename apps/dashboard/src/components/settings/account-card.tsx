import { Card } from "@stark/ui/components/card";
import { SignOut } from "@/components/settings/sign-out";

export function AccountCard() {
  return (
    <Card className="gap-2">
      <span className="font-medium">Signed in</span>
      <p className="m-0 text-sm text-fg-2">
        Stark only ever pays from the wallet in this account. Logging out ends the session on the
        server, not just in this tab.
      </p>
      <SignOut />
    </Card>
  );
}
