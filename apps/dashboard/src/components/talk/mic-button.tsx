import { Button } from "@stark/ui/components/button";
import { Icons } from "@stark/ui/components/icons";
import { cn } from "@stark/ui/utils/cn";
import type { Stage } from "@/lib/talk/types";

export function MicButton({
  stage,
  live,
  onTap,
}: {
  stage: Stage;
  live: boolean;
  onTap: () => void;
}) {
  return (
    <Button
      variant="ghost"
      onClick={onTap}
      disabled={stage === "thinking"}
      aria-label={stage === "listening" ? "Stop recording" : "Talk to Stark"}
      className={cn(
        "relative z-10 size-50 rounded-full lg:size-64",
        live
          ? "border-0 bg-brand-warm text-canvas-deep shadow-[0_0_0_16px_var(--color-brand-tint),0_0_0_36px_var(--color-brand-wash)] hover:bg-brand-warm hover:text-canvas-deep"
          : "border-line-2 bg-surface text-fg shadow-[0_0_0_16px_var(--color-line)] hover:bg-surface-2 hover:text-fg",
      )}
    >
      <Icons.Mic className="size-14 lg:size-18" />
    </Button>
  );
}
