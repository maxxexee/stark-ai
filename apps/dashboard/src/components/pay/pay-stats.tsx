import { Stat, StatGrid } from "@stark/ui/components/stat";
import { formatNaira } from "@stark/utils/format";

export function PayStats({
  remaining,
  amount,
  fee,
}: {
  remaining: number;
  amount: number;
  fee: number;
}) {
  return (
    <StatGrid className="grid-cols-2">
      <Stat label="From">Your wallet</Stat>
      <Stat label="Left this month after">
        {formatNaira(Math.max(0, remaining - amount - fee))}
      </Stat>
      {fee > 0 ? <Stat label="Service fee">{formatNaira(fee)}</Stat> : null}
    </StatGrid>
  );
}
