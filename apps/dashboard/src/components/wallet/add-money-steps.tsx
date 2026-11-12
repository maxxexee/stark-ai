import { cn } from "@stark/ui/utils/cn";

const STEPS = ["Amount", "Pay", "Done"] as const;

/**
 * Past the first step, Amount is a button back to the card (`onBackToAmount`) with what was entered
 * still filled in.
 */
export function AddMoneySteps({
  current,
  onBackToAmount,
}: {
  current: 1 | 2 | 3;
  onBackToAmount?: () => void;
}) {
  return (
    <ol aria-label="Adding money" className="m-0 flex list-none gap-2 p-0">
      {STEPS.map((label, i) => {
        const step = i + 1;
        const bar = (
          <>
            <span
              className={cn("h-1 w-full rounded-lg", step <= current ? "bg-brand" : "bg-track")}
            />
            <span className={cn("text-sm", step === current ? "text-fg" : "text-fg-2")}>
              {label}
            </span>
          </>
        );
        return (
          <li key={label} aria-current={step === current ? "step" : undefined} className="flex-1">
            {step === 1 && onBackToAmount ? (
              <button
                type="button"
                onClick={onBackToAmount}
                aria-label="Back to amount"
                className="flex w-full cursor-pointer flex-col items-start gap-1.5 rounded-lg text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50 [&>span:last-child]:underline-offset-4 hover:[&>span:last-child]:text-fg hover:[&>span:last-child]:underline"
              >
                {bar}
              </button>
            ) : (
              <div className="flex flex-col items-start gap-1.5">{bar}</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
