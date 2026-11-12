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
import type { StatusCount } from "@/lib/admin/admin-api";

export function AdminStatusTable({ title, rows }: { title: string; rows: StatusCount[] }) {
  return (
    <Card>
      <Eyebrow>{title}</Eyebrow>
      {rows.length === 0 ? (
        <p className="m-0 text-sm text-muted-foreground">None yet.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Method</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Count</TableHead>
              <TableHead className="text-right">Amount</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={`${row.method}:${row.status}`}>
                <TableCell>{row.method}</TableCell>
                <TableCell>{row.status}</TableCell>
                <TableCell className="tabular text-right">{row.count}</TableCell>
                <TableCell className="tabular text-right">{formatNaira(row.amount_ngn)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}
