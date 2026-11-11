import { errorCopy } from "@stark/api/errors";
import { useResolveBankAccount, useWithdraw } from "@stark/api/mutations";
import type { Bank, Withdrawal } from "@stark/api/types";
import { AmountField } from "@stark/ui/components/amount-field";
import { Button } from "@stark/ui/components/button";
import { FieldError } from "@stark/ui/components/field";
import { Spinner } from "@stark/ui/components/spinner";
import { TextField } from "@stark/ui/components/text-field";
import { formatNaira } from "@stark/utils/format";
import { useState } from "react";
import { BankSelect } from "@/components/wallet/bank-select";

/**
 * Bank, account number, amount. The account name is checked with the bank before
 * anything is sent, so the user sees whose account it is.
 */
export function WithdrawForm({
  banks,
  balance,
  onSent,
}: {
  banks: Bank[];
  balance: number;
  onSent: (withdrawal: Withdrawal) => void;
}) {
  const [bankCode, setBankCode] = useState("");
  const [accountNumber, setAccountNumber] = useState("");
  const [amount, setAmount] = useState(Math.min(10000, balance));
  const resolve = useResolveBankAccount();
  const withdraw = useWithdraw();

  const lookUp = (code: string, number: string) => {
    resolve.reset();
    if (code && number.length === 10) {
      resolve.mutate({ bank_code: code, account_number: number });
    }
  };

  const handleBank = (code: string) => {
    setBankCode(code);
    lookUp(code, accountNumber);
  };

  const handleAccountNumber = (value: string) => {
    const digits = value.replace(/\D/g, "").slice(0, 10);
    setAccountNumber(digits);
    lookUp(bankCode, digits);
  };

  const handleSend = () =>
    withdraw.mutate(
      { bank_code: bankCode, account_number: accountNumber, amount_ngn: amount },
      { onSuccess: onSent },
    );

  const error = withdraw.error ?? resolve.error;

  return (
    <div className="flex flex-col gap-6">
      <BankSelect banks={banks} value={bankCode} onChange={handleBank} />
      <TextField
        label="Account number"
        inputMode="numeric"
        autoComplete="off"
        value={accountNumber}
        onChange={(event) => handleAccountNumber(event.target.value)}
        hint={resolve.data ? resolve.data.account_name : "10 digits"}
      />
      <AmountField label="Amount" value={amount} onChange={setAmount} />
      {error ? <FieldError className="text-sm">{errorCopy(error)}</FieldError> : null}
      <Button
        size="lg"
        block
        disabled={!resolve.data || amount < 100 || amount > balance || withdraw.isPending}
        onClick={handleSend}
      >
        {withdraw.isPending ? <Spinner /> : null}
        {resolve.data
          ? `Send ${formatNaira(amount)} to ${resolve.data.account_name}`
          : `Send ${formatNaira(amount)}`}
      </Button>
    </div>
  );
}
