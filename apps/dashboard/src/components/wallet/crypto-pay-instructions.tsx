import type { Deposit } from "@stark/api/types";
import { Card } from "@stark/ui/components/card";
import { Eyebrow } from "@stark/ui/components/eyebrow";
import { AddressQrCode } from "@/components/wallet/address-qr-code";
import { CopyIconButton } from "@/components/wallet/copy-icon-button";
import { CopyableField } from "@/components/wallet/copyable-field";
import { Networks } from "@/lib/wallet/networks";

type CryptoPay = Extract<Deposit, { method: "crypto" }>["pay"];

/** Exactly what to send, where. A wrong amount or a missing memo is refunded, not credited. */
export function CryptoPayInstructions({ pay }: { pay: CryptoPay }) {
  return (
    <Card className="gap-4">
      <div className="flex flex-col gap-1">
        <Eyebrow>Send exactly</Eyebrow>
        <div className="flex items-center gap-2">
          <span className="text-2xl font-medium tabular-nums">
            {pay.amount} {pay.asset}
          </span>
          <CopyIconButton value={pay.amount} label="Copy amount" />
        </div>
        <span className="text-xs text-muted-foreground">
          On the {Networks.name(pay.chain)} network only.
        </span>
      </div>
      <div className="flex flex-col gap-2">
        <Eyebrow>To</Eyebrow>
        <AddressQrCode address={pay.address} />
        <CopyableField value={pay.address} label="Copy address" />
      </div>
      {pay.memo ? (
        <div className="flex flex-col gap-2">
          <Eyebrow>With this memo</Eyebrow>
          <CopyableField value={pay.memo} label="Copy memo" />
        </div>
      ) : null}
    </Card>
  );
}
