import { InputGroupButton } from "@stark/ui/components/input-group";
import { useState } from "react";
import { ClipboardCheck as ClipboardCheckIcon, Clipboard as ClipboardIcon } from "reicon-react";

export function CopyIconButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <InputGroupButton
      size="icon-sm"
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
      onClick={handleCopy}
    >
      {copied ? <ClipboardCheckIcon /> : <ClipboardIcon />}
    </InputGroupButton>
  );
}
