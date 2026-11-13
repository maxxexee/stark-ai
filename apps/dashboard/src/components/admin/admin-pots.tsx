import { Card } from "@stark/ui/components/card";
import { Eyebrow } from "@stark/ui/components/eyebrow";
import { Stat, StatGrid } from "@stark/ui/components/stat";
import { cn } from "@stark/ui/utils/cn";
import { formatNaira } from "@stark/utils/format";
import type { TreasuryReport } from "@/lib/admin/admin-api";

/** Both pots against what users are owed. Coverage below zero means Stark owes more than it holds. */
export function AdminPots({ report }: { report: TreasuryReport }) {
  const { held, treasury_usdc: usdc, vaults } = report;
  const short = report.coverage_ngn < 0;
  return (
    <Card>
      <div className="flex flex-col gap-1">
        <Eyebrow>Coverage</Eyebrow>
        <span
          className={cn(
            "tabular text-3xl font-semibold tracking-tight",
            short && "text-destructive",
          )}
        >
          {formatNaira(report.coverage_ngn)}
        </span>
        <span className="text-sm text-muted-foreground">
          {short ? "Stark owes users more than it holds." : "Held minus owed to users."}
        </span>
      </div>
      <StatGrid>
        <Stat label="Flutterwave">
          {held.flutterwave_ngn === null ? "Unreadable" : formatNaira(held.flutterwave_ngn)}
        </Stat>
        <Stat label="Pending purchases">{formatNaira(held.pending_purchases_ngn)}</Stat>
        <Stat label="Treasury">{usdc === null ? "Unreadable" : `${usdcText(usdc)} USDC`}</Stat>
        <Stat label="Treasury in naira">
          {held.treasury_usdc_as_ngn === null
            ? "Unreadable"
            : formatNaira(held.treasury_usdc_as_ngn)}
        </Stat>
        {vaults && (
          <>
            <Stat label={vaults.count === null ? "Vaults" : `${vaults.count} vaults`}>
              {`${usdcText(vaults.usdc ?? "0")} USDC`}
            </Stat>
            <Stat
              label={vaults.counted ? "Vaults in naira" : `Vaults in naira (${vaults.network})`}
            >
              {`${formatNaira(held.vaults_usdc_as_ngn ?? 0)}${vaults.counted ? "" : ", not counted"}`}
            </Stat>
          </>
        )}
        <Stat label="Owed to users">{formatNaira(report.owed_to_users_ngn)}</Stat>
        <Stat label="Vault ops not settled">{report.unsettled_vault_ops}</Stat>
      </StatGrid>
    </Card>
  );
}

function usdcText(usdc: string) {
  return Number(usdc).toLocaleString("en-NG", { maximumFractionDigits: 2 });
}
