import { Icons } from "@stark/ui/components/icons";

export function PasswordRevealButton({
  revealed,
  onToggle,
}: {
  revealed: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={revealed}
      aria-label={revealed ? "Hide password" : "Show password"}
      className="grid size-8 shrink-0 cursor-pointer place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-surface-2 hover:text-fg focus-visible:ring-2 focus-visible:ring-brand focus-visible:outline-none"
    >
      {revealed ? <Icons.EyeOff size={16} /> : <Icons.Eye size={16} />}
    </button>
  );
}
