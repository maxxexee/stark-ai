import { activityQuery } from "@stark/api/queries";
import { isToday } from "@stark/utils/format";
import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { ActivityEmpty } from "@/components/activity/activity-empty";
import { ActivityFilters } from "@/components/activity/activity-filters";
import { ActivitySection } from "@/components/activity/activity-section";
import { ReceiptSheet } from "@/components/activity/receipt-sheet";
import { PageTitle } from "@/components/shell/page-title";
import { Receipts } from "@/lib/receipts/receipts";

export const Route = createFileRoute("/_app/activity")({
  validateSearch: z.object({
    filter: z.enum(["all", "bills", "in", "declined"]).optional(),
    receipt: z.string().optional(),
    bill: z.string().optional(),
  }),
  loader: ({ context }) => context.queryClient.query({ ...activityQuery(), staleTime: "static" }),
  head: () => ({ meta: [{ title: "Activity · Stark" }] }),
  component: Activity,
});

function Activity() {
  const { data } = useSuspenseQuery(activityQuery());
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  const filter = search.filter ?? "all";

  const rows = data.filter(
    (r) => Receipts.matchesFilter(r, filter) && (!search.bill || r.bill_id === search.bill),
  );
  const selected = rows.find((r) => r.id === search.receipt);
  const today = rows.filter((r) => isToday(r.created_at));
  const earlier = rows.filter((r) => !isToday(r.created_at));

  return (
    <>
      <PageTitle>Activity</PageTitle>
      <ActivityFilters
        value={filter}
        onChange={(value) =>
          navigate({
            search: (prev) => ({
              ...prev,
              filter: value === "all" ? undefined : value,
              receipt: undefined,
            }),
          })
        }
      />

      {today.length ? (
        <ActivitySection title="Today" receipts={today} selectedId={selected?.id} />
      ) : null}
      {earlier.length ? (
        <ActivitySection title="Earlier" receipts={earlier} selectedId={selected?.id} />
      ) : null}
      {!rows.length ? <ActivityEmpty /> : null}

      <ReceiptSheet
        receipt={selected}
        onClose={() => navigate({ search: (prev) => ({ ...prev, receipt: undefined }) })}
      />
    </>
  );
}
