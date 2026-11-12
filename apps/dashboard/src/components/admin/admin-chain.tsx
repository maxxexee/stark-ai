import { Card } from "@stark/ui/components/card";
import { Eyebrow } from "@stark/ui/components/eyebrow";
import { Stat, StatGrid } from "@stark/ui/components/stat";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@stark/ui/components/table";
import { formatDistanceToNow } from "date-fns";
import type { AdminOverview } from "@/lib/admin/admin-api";

/** The chain Stark runs on, the server's outbound IP, and every user's vault. */
export function AdminChain({
  chain,
  vaults,
  egressIp,
}: {
  chain: AdminOverview["chain"];
  vaults: AdminOverview["vaults"];
  egressIp: string | null;
}) {
  const explorer =
    chain?.network === "mainnet" ? "https://nearblocks.io" : "https://testnet.nearblocks.io";
  return (
    <Card>
      <Eyebrow>Chain</Eyebrow>
      <StatGrid>
        <Stat label="Network">{chain?.network ?? "Off chain"}</Stat>
        <Stat label="Funder and treasury">
          {chain ? (
            <a
              href={`${explorer}/address/${chain.funder}`}
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-4"
            >
              {chain.funder}
            </a>
          ) : (
            "None"
          )}
        </Stat>
        <Stat label="Server IP">
          <span className="font-mono text-sm">{egressIp ?? "Unreadable"}</span>
        </Stat>
      </StatGrid>
      {vaults.length === 0 ? (
        <p className="m-0 text-sm text-muted-foreground">No vaults yet.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Vault</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Age</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {vaults.map((vault) => (
              <TableRow key={vault.account_id}>
                <TableCell className="font-mono text-xs">
                  <a
                    href={`${explorer}/address/${vault.account_id}`}
                    target="_blank"
                    rel="noreferrer"
                    className="underline underline-offset-4"
                  >
                    {vault.account_id}
                  </a>
                </TableCell>
                <TableCell className="font-mono text-xs">{vault.user_id}</TableCell>
                <TableCell title={vault.last_error ?? undefined}>{vault.status}</TableCell>
                <TableCell className="text-right text-muted-foreground">
                  {formatDistanceToNow(vault.created_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}
