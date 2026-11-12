import { errorCopy } from "@stark/api/errors";
import { useWithdrawCrypto } from "@stark/api/mutations";
import { cryptoAssetsQuery, usdcRatesQuery } from "@stark/api/queries";
import type { Withdrawal } from "@stark/api/types";
import { AmountField } from "@stark/ui/components/amount-field";
import { Button } from "@stark/ui/components/button";
import { FieldError } from "@stark/ui/components/field";
import { Spinner } from "@stark/ui/components/spinner";
import { TextField } from "@stark/ui/components/text-field";
import { formatNaira } from "@stark/utils/format";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CryptoAssetSelect } from "@/components/wallet/crypto-asset-select";

// The server's floor for a crypto withdrawal; below it the swap fees eat the payout.
const MIN_CRYPTO_NGN = 1000;

/**
 * What to receive, where, and how much. The server checks the address against the
 * asset's chain when it prices the swap, so a wrong one is refused before anything
 * leaves the balance.
 */
export function CryptoWithdrawForm({
  balance,
  onSent,
}: {
  balance: number;
  onSent: (withdrawal: Withdrawal) => void;
}) {
  const assets = useQuery(cryptoAssetsQuery());
  const rates = useQuery(usdcRatesQuery());
  const [assetId, setAssetId] = useState("");
  const [address, setAddress] = useState("");
  const [amount, setAmount] = useState(Math.min(20000, balance));
  const withdraw = useWithdrawCrypto();

  const asset = assets.data?.find((a) => a.asset_id === assetId);

  const handleSend = () =>
    withdraw.mutate(
      { amount_ngn: amount, asset_id: assetId, address: address.trim() },
      { onSuccess: onSent },
    );

  return (
    <div className="flex flex-col gap-6">
      <CryptoAssetSelect
        label="Receive as"
        placeholder="Choose what to receive"
        assets={assets.data ?? []}
        value={assetId}
        onChange={setAssetId}
      />
      <TextField
        label="Your address"
        autoComplete="off"
        spellCheck={false}
        value={address}
        onChange={(event) => setAddress(event.target.value)}
        hint={asset ? `A ${asset.symbol} address on ${asset.chain}` : "Pick what to receive first"}
      />
      <AmountField label="Amount" value={amount} onChange={setAmount} />
      {rates.data ? (
        <p className="m-0 text-sm text-fg-2">
          About {(amount / Number(rates.data.withdraw)).toFixed(2)} USDC at{" "}
          {formatNaira(Number(rates.data.withdraw))} per USDC, before swap fees.
        </p>
      ) : null}
      {assets.error ? <FieldError className="text-sm">{errorCopy(assets.error)}</FieldError> : null}
      {withdraw.error ? (
        <FieldError className="text-sm">{errorCopy(withdraw.error)}</FieldError>
      ) : null}
      <Button
        size="lg"
        block
        disabled={
          !asset ||
          !address.trim() ||
          amount < MIN_CRYPTO_NGN ||
          amount > balance ||
          withdraw.isPending
        }
        onClick={handleSend}
      >
        {withdraw.isPending ? <Spinner /> : null}
        {asset ? `Send ${formatNaira(amount)} as ${asset.symbol}` : `Send ${formatNaira(amount)}`}
      </Button>
    </div>
  );
}
