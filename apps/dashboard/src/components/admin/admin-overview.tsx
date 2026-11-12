import { ApiError } from "@stark/api/errors";
import { Button } from "@stark/ui/components/button";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { AdminChain } from "@/components/admin/admin-chain";
import { AdminFees } from "@/components/admin/admin-fees";
import { AdminInFlightTable } from "@/components/admin/admin-in-flight-table";
import { AdminPots } from "@/components/admin/admin-pots";
import { AdminStatusTable } from "@/components/admin/admin-status-table";
import { AdminApi } from "@/lib/admin/admin-api";

export function AdminOverview({
  adminKey,
  onRefused,
  onLock,
}: {
  adminKey: string;
  onRefused: (message: string) => void;
  onLock: () => void;
}) {
  const { data, error, dataUpdatedAt, isFetching, refetch } = useQuery({
    queryKey: ["admin", "overview", adminKey],
    queryFn: () => AdminApi.overview(adminKey),
    refetchInterval: 30_000,
    retry: false,
  });

  useEffect(() => {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      onRefused(error.message);
    }
  }, [error, onRefused]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-sm text-muted-foreground">
          {dataUpdatedAt ? `Updated ${new Date(dataUpdatedAt).toLocaleTimeString()}` : "Loading…"}
        </span>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => refetch()} disabled={isFetching}>
            Refresh
          </Button>
          <Button variant="ghost" onClick={onLock}>
            Lock
          </Button>
        </div>
      </div>
      {error && !data ? <p className="m-0 text-sm text-destructive">{error.message}</p> : null}
      {data ? (
        <>
          <AdminPots report={data.treasury} />
          {data.fees_ngn ? (
            <AdminFees
              key={JSON.stringify(data.fees_ngn)}
              adminKey={adminKey}
              fees={data.fees_ngn}
            />
          ) : null}
          <div className="grid gap-6 md:grid-cols-2">
            <AdminStatusTable title="Deposits" rows={data.deposits} />
            <AdminStatusTable title="Withdrawals" rows={data.withdrawals} />
          </div>
          <AdminInFlightTable title="Withdrawals in flight" rows={data.withdrawals_in_flight} />
          <AdminInFlightTable title="Deposits open" rows={data.deposits_open} />
          <AdminChain chain={data.chain} vaults={data.vaults} egressIp={data.egress_ip} />
        </>
      ) : null}
    </div>
  );
}
