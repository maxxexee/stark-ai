import { MethodIcon } from "@/components/auth/method-icon";
import type { Method } from "@/components/auth/methods";

const COPY: Record<Exclude<Method, "email">, string> = {
  google: "We'll hand you to Google, then straight back here.",
};

export function MethodNote({ method }: { method: Exclude<Method, "email"> }) {
  return (
    <div className="flex flex-1 flex-col justify-center gap-4 rounded-card border border-border bg-surface-2 p-4">
      <span className="grid size-8 place-items-center rounded-lg border border-border bg-card">
        <MethodIcon method={method} />
      </span>
      <p className="m-0 max-w-[26ch] text-base text-fg-2">{COPY[method]}</p>
    </div>
  );
}
