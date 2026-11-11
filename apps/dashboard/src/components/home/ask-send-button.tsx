import { Icons } from "@stark/ui/components/icons";
import { InputGroupButton } from "@stark/ui/components/input-group";

export function AskSendButton() {
  return (
    <InputGroupButton type="submit" variant="default" size="icon-sm" aria-label="Send">
      <Icons.ArrowRight className="size-4" />
    </InputGroupButton>
  );
}
