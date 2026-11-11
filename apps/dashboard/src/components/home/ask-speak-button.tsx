import { Icons } from "@stark/ui/components/icons";
import { InputGroupButton } from "@stark/ui/components/input-group";
import { Link } from "@tanstack/react-router";

export function AskSpeakButton() {
  return (
    <InputGroupButton
      variant="default"
      size="icon-sm"
      aria-label="Speak instead"
      nativeButton={false}
      render={<Link to="/talk" />}
    >
      <Icons.Mic className="size-4" />
    </InputGroupButton>
  );
}
