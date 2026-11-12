import { cn } from "@stark/ui/utils/cn";
import { MethodIcon } from "@/components/auth/method-icon";
import type { Method } from "@/components/auth/methods";

export function MethodPickerOption({
  method,
  label,
  active,
  onSelect,
}: {
  method: Method;
  label: string;
  active: boolean;
  onSelect: (method: Method) => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() => onSelect(method)}
      className={cn(
        "flex h-9 cursor-pointer items-center justify-center gap-2 rounded-lg border px-3 text-sm font-medium shadow-control transition-colors",
        "focus-visible:border-brand focus-visible:ring-3 focus-visible:ring-brand/25 focus-visible:outline-none",
        active
          ? "border-brand-line bg-brand-wash text-brand"
          : "border-border bg-card text-fg-2 hover:bg-surface-2 hover:text-fg",
      )}
    >
      <MethodIcon method={method} />
      {label}
    </button>
  );
}
