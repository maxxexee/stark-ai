import { Icons } from "@stark/ui/components/icons";

export function LimitsNote() {
  return (
    <div className="mt-8 flex items-start gap-2 border-t border-border pt-6 text-sm text-muted-foreground">
      <Icons.Lock size={14} className="mt-0.5 shrink-0" />
      <span>Stark can only pay the bills you add, inside limits only you can change.</span>
    </div>
  );
}
