import { Button } from "@stark/ui/components/button";
import { Icons } from "@stark/ui/components/icons";
import { Link } from "@tanstack/react-router";

export function TalkCloseButton() {
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Close"
      nativeButton={false}
      render={<Link to="/" />}
    >
      <Icons.Close />
    </Button>
  );
}
