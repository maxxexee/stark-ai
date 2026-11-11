import { Icons } from "@stark/ui/components/icons";

export function LimitHint({ hint }: { hint: string | null }) {
  return hint ? (
    <p className="m-0 flex items-center gap-2 text-sm text-brand">
      <Icons.Warning size={16} />
      {hint}
    </p>
  ) : (
    <p className="m-0 flex items-center gap-2 text-sm text-fg-2">
      <Icons.Shield size={16} className="text-muted-foreground" />
      Within your spending limits
    </p>
  );
}
