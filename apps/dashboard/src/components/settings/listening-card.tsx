import { Button } from "@stark/ui/components/button";
import { Card } from "@stark/ui/components/card";
import { Icons } from "@stark/ui/components/icons";
import { Link } from "@tanstack/react-router";

export function ListeningCard() {
  return (
    <Card className="gap-2">
      <span className="font-medium">Telegram and the wall phone</span>
      <p className="m-0 text-sm text-fg-2">
        Voice notes only count when they include the word “Stark”, so everyday talk in the room
        never triggers a payment.
      </p>
      <Button
        variant="secondary"
        nativeButton={false}
        render={<Link to="/connect" />}
        className="self-start"
      >
        <Icons.Telegram size={16} />
        Connect a chat
      </Button>
    </Card>
  );
}
