import { InputGroup, InputGroupAddon } from "@stark/ui/components/input-group";
import { CopyIconButton } from "@/components/wallet/copy-icon-button";

/** A value on one line, never truncated (a long one scrolls sideways on a narrow screen),
 * with a copy button inside the field. */
export function CopyableField({ value, label }: { value: string; label: string }) {
  return (
    <InputGroup className="pl-3">
      <span className="no-scrollbar min-w-0 flex-1 overflow-x-auto whitespace-nowrap font-mono text-sm">
        {value}
      </span>
      <InputGroupAddon align="inline-end">
        <CopyIconButton value={value} label={label} />
      </InputGroupAddon>
    </InputGroup>
  );
}
