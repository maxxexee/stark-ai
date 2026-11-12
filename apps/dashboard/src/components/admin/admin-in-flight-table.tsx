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
import { formatNaira } from "@stark/utils/format";
import { formatDistanceToNow } from "date-fns";

/** Deposits still open, or withdrawals not yet paid: the rows worth a look when something is stuck. */
export function AdminInFlightTable({
  title,
  rows,
}: {
  title: string;
  rows: {
    id: string;
    user_id: string;
    method: string;
    amount_ngn: number;
    status: string;
    created_at: string;
  }[];
}) {
  return (
    <Card>
      <Eyebrow>{title}</Eyebrow>
      {rows.length === 0 ? (
        <p className="m-0 text-sm text-muted-foreground">Nothing in flight.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Id</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Method</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Amount</TableHead>
              <TableHead className="text-right">Age</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-mono text-xs">{row.id}</TableCell>
                <TableCell className="font-mono text-xs">{row.user_id}</TableCell>
                <TableCell>{row.method}</TableCell>
                <TableCell>{row.status}</TableCell>
                <TableCell className="tabular text-right">{formatNaira(row.amount_ngn)}</TableCell>
                <TableCell className="text-right text-muted-foreground">
                  {formatDistanceToNow(row.created_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}
