import { InputGroup, InputGroupAddon, InputGroupInput } from "@stark/ui/components/input-group";
import { useNavigate } from "@tanstack/react-router";
import { type SubmitEvent, useState } from "react";
import { AskSendButton } from "@/components/home/ask-send-button";
import { AskSpeakButton } from "@/components/home/ask-speak-button";

export function AskStark() {
  const navigate = useNavigate();
  const [text, setText] = useState("");

  const handleAskStark = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (text.trim()) navigate({ to: "/talk", search: { q: text.trim() } });
  };

  return (
    <form className="m-0" onSubmit={handleAskStark}>
      <InputGroup className="h-10 pr-1 pl-3">
        <InputGroupInput
          aria-label="Ask Stark"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ask Stark: “buy 2GB for my line”"
          className="h-full px-0 py-0 text-base shadow-none"
        />
        <InputGroupAddon align="inline-end" className="py-0 pr-0 has-[>button]:mr-0">
          {text.trim() ? <AskSendButton /> : <AskSpeakButton />}
        </InputGroupAddon>
      </InputGroup>
    </form>
  );
}
