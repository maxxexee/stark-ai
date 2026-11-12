import { Icons } from "@stark/ui/components/icons";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@stark/ui/components/input-group";
import { type SubmitEvent, useState } from "react";

export function TypeForm({
  thinking,
  onSend,
}: {
  thinking: boolean;
  onSend: (text: string) => void;
}) {
  const [typed, setTyped] = useState("");

  const handleSendTyped = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = typed.trim();
    if (!text) return;
    setTyped("");
    onSend(text);
  };

  return (
    <form className="m-0" onSubmit={handleSendTyped}>
      <InputGroup className="h-10 pr-1 pl-1">
        <InputGroupInput
          id="type-instead"
          aria-label="Type instead"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder="Or type it"
          className="h-full text-base"
        />
        <InputGroupAddon align="inline-end" className="py-0">
          <InputGroupButton
            type="submit"
            variant="default"
            size="icon-sm"
            aria-label="Send"
            disabled={!typed.trim() || thinking}
          >
            <Icons.ArrowRight />
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
    </form>
  );
}
