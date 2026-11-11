import { cn } from "@stark/ui/utils/cn";
import { type ReactNode, type Ref, useId } from "react";

/** One side of the Add money card: a label, a big amount and what it is in. */
export function SwapPanel({
  label,
  value,
  onChange,
  inputMode,
  pending,
  currency,
  ref,
}: {
  label: string;
  value: string;
  onChange: (raw: string) => void;
  inputMode: "numeric" | "decimal";
  pending: boolean;
  currency: ReactNode;
  ref?: Ref<HTMLDivElement>;
}) {
  const id = useId();
  return (
    <div ref={ref} className="flex flex-col gap-2 rounded-xl bg-canvas px-4 pt-3 pb-4">
      <label htmlFor={id} className="text-[13px] text-fg-2">
        {label}
      </label>
      <div className="flex items-center gap-3">
        <input
          id={id}
          inputMode={inputMode}
          autoComplete="off"
          placeholder="0"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className={cn(
            "tabular min-w-0 flex-1 bg-transparent font-serif text-[28px] outline-none placeholder:text-muted-foreground",
            pending && "opacity-50",
          )}
        />
        {currency}
      </div>
    </div>
  );
}
