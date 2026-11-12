import { Stat, StatGrid } from "@stark/ui/components/stat";
import { formatNaira } from "@stark/utils/format";

export function PayStats({ remaining, amount }: { remaining: number; amount: number }) {
  return (
    <StatGrid className="grid-cols-2">
      <Stat label="From">Your wallet</Stat>
      <Stat label="Left this month after">{formatNaira(Math.max(0, remaining - amount))}</Stat>
    </StatGrid>
  );
}
