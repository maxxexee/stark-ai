import { Card } from "@stark/ui/components/card";
import { Eyebrow } from "@stark/ui/components/eyebrow";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@stark/ui/components/table";
import { formatDistanceToNow } from "date-fns";
import type { StuckChainOp } from "@/lib/admin/admin-api";

/** Chain ops that have not gone through. A user's payments wait behind any of theirs
 * still pending, so the chain's own error here is usually the whole answer. */
export function AdminChainOps({ ops }: { ops: StuckChainOp[] }) {
  return (
    <Card>
      <Eyebrow>Stuck on chain</Eyebrow>
      {ops.length === 0 ? (
        <p className="m-0 text-sm text-muted-foreground">Nothing waiting.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Op</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Last error</TableHead>
              <TableHead className="text-right">Age</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {ops.map((op) => (
              <TableRow key={op.id}>
                <TableCell className="font-mono text-xs">
                  {op.method} · {op.attempts} tries
                </TableCell>
                <TableCell className="font-mono text-xs">{op.user_id}</TableCell>
                <TableCell>{op.status}</TableCell>
                <TableCell className="max-w-md text-xs whitespace-normal break-words">
                  {op.last_error ?? "Not sent yet"}
                </TableCell>
                <TableCell className="text-right text-muted-foreground">
                  {formatDistanceToNow(op.created_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}
