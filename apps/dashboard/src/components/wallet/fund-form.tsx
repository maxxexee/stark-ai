import { errorCopy } from "@stark/api/errors";
import { useTopUp } from "@stark/api/mutations";
import { AmountField } from "@stark/ui/components/amount-field";
import { Button } from "@stark/ui/components/button";
import { FieldError } from "@stark/ui/components/field";
import { Spinner } from "@stark/ui/components/spinner";
import { formatNaira } from "@stark/utils/format";
import { requestId } from "@stark/utils/id";
import { useMemo, useState } from "react";
import { TestMoneyNote } from "@/components/wallet/test-money-note";

export function FundForm({ onDone }: { onDone: () => void }) {
  const [amount, setAmount] = useState(20000);
  const topUp = useTopUp();

  const key = useMemo(() => requestId("dep"), [amount]);

  const handleAddTestMoney = () =>
    topUp.mutate({ amount_ngn: amount, request_id: key }, { onSuccess: onDone });

  return (
    <div className="flex flex-col gap-6">
      <AmountField
        label="Amount"
        value={amount}
        onChange={setAmount}
        presets={[10000, 20000, 50000]}
      />
      <TestMoneyNote />
      {topUp.error ? <FieldError className="text-sm">{errorCopy(topUp.error)}</FieldError> : null}
      <Button
        size="lg"
        block
        disabled={amount <= 0 || topUp.isPending}
        onClick={handleAddTestMoney}
      >
        {topUp.isPending ? <Spinner /> : null}
        {topUp.isPending ? "Adding…" : `Add ${formatNaira(amount)} test money`}
      </Button>
    </div>
  );
}
