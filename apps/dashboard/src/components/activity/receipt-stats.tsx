import type { Receipt } from "@stark/api/types";
import { Stat, StatGrid } from "@stark/ui/components/stat";
import { formatNaira } from "@stark/utils/format";
import { NearExplorer } from "@/lib/receipts/near-explorer";

export function ReceiptStats({ receipt }: { receipt: Receipt }) {
  return (
    <StatGrid>
      {receipt.source ? <Stat label="Asked via">{receipt.source}</Stat> : null}
      {receipt.units ? <Stat label="Units">{receipt.units} kWh</Stat> : null}
      {receipt.fee_ngn ? <Stat label="Service fee">{formatNaira(receipt.fee_ngn)}</Stat> : null}
      <Stat label="Receipt ID">
        <span className="tabular">{receipt.id.toUpperCase()}</span>
      </Stat>
      {receipt.tx_hash ? (
        <Stat label="Approved by">
          <a
            href={NearExplorer.transaction(receipt.tx_hash)}
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-4"
          >
            View on NEAR
          </a>
        </Stat>
      ) : null}
    </StatGrid>
  );
}
