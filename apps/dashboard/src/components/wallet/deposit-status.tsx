import { depositQuery } from "@stark/api/queries";
import { useQuery } from "@tanstack/react-query";
import { AddMoneySteps } from "@/components/wallet/add-money-steps";
import { DepositStage } from "@/components/wallet/deposit-stage";

export function DepositStatus({
  depositId,
  onBackToAmount,
}: {
  depositId: string;
  onBackToAmount: () => void;
}) {
  const { data: deposit } = useQuery(depositQuery(depositId));
  return (
    <div className="flex flex-col gap-6">
      <AddMoneySteps
        current={deposit?.status === "credited" ? 3 : 2}
        onBackToAmount={onBackToAmount}
      />
      <DepositStage depositId={depositId} />
    </div>
  );
}
