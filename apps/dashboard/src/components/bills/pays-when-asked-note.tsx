import { limitsQuery } from "@stark/api/queries";
import { Icons } from "@stark/ui/components/icons";
import { formatNaira } from "@stark/utils/format";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

export function PaysWhenAskedNote() {
  const { data: limits } = useQuery(limitsQuery());
  return (
    <p className="m-0 flex items-start gap-2 text-sm text-fg-2">
      <Icons.Shield size={16} className="flex-none text-muted-foreground" />
      <span>
        Stark pays only when you ask
        {limits ? `, up to ${formatNaira(limits.monthly_cap_ngn)} a month` : ""}.{" "}
        <Link to="/settings">Change</Link>
      </span>
    </p>
  );
}
