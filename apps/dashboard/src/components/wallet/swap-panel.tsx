import { Spinner } from "@stark/ui/components/spinner";
import { cn } from "@stark/ui/utils/cn";
import { type ReactNode, type Ref, type RefObject, useId, useLayoutEffect, useRef } from "react";

/**
 * The label and the figure are one <label>, so a click anywhere left of the currency chip lands in
 * the amount. Reformatting adds or drops commas, so the caret is restored after the same number of
 * digits.
 */
export function SwapPanel({
  label,
  value,
  onChange,
  inputMode,
  pending,
  currency,
  ref,
  inputRef,
}: {
  label: string;
  value: string;
  onChange: (raw: string) => void;
  inputMode: "numeric" | "decimal";
  pending: boolean;
  currency: ReactNode;
  ref?: Ref<HTMLDivElement>;
  inputRef?: RefObject<HTMLInputElement | null>;
}) {
  const id = useId();
  const ownInput = useRef<HTMLInputElement>(null);
  const input = inputRef ?? ownInput;
  const caretDigits = useRef<number | null>(null);

  useLayoutEffect(() => {
    const el = input.current;
    if (caretDigits.current === null || !el || document.activeElement !== el) return;
    let seen = 0;
    let at = 0;
    while (at < value.length && seen < caretDigits.current) {
      if (/[0-9.]/.test(value[at] ?? "")) seen++;
      at++;
    }
    el.setSelectionRange(at, at);
    caretDigits.current = null;
  }, [value, input]);

  return (
    <div
      ref={ref}
      className="flex items-end gap-3 rounded-lg bg-card pr-4 transition-shadow has-[input:focus]:ring-2 has-[input:focus]:ring-ring/30"
    >
      <label htmlFor={id} className="flex min-w-0 flex-1 cursor-text flex-col gap-3 py-3.5 pl-4">
        <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
          {label}
          {pending ? <Spinner className="size-3.5" aria-label="Updating" /> : null}
        </span>
        <input
          ref={input}
          id={id}
          inputMode={inputMode}
          enterKeyHint="go"
          autoComplete="off"
          placeholder="0"
          aria-busy={pending}
          value={value}
          onChange={(event) => {
            const el = event.target;
            const beforeCaret = el.value.slice(0, el.selectionStart ?? el.value.length);
            caretDigits.current = beforeCaret.replace(/[^0-9.]/g, "").length;
            onChange(el.value);
          }}
          className={cn(
            "tabular h-10 w-full min-w-0 bg-transparent p-0 text-3xl font-normal tracking-tight outline-none placeholder:text-muted-foreground",
            pending && "opacity-50 motion-safe:animate-pulse",
          )}
        />
      </label>
      <div className="mb-4 flex-none">{currency}</div>
    </div>
  );
}
