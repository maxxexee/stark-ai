import { ApiError } from "@stark/api/errors";
import { Button } from "@stark/ui/components/button";
import { Card } from "@stark/ui/components/card";
import { Eyebrow } from "@stark/ui/components/eyebrow";
import { TextField } from "@stark/ui/components/text-field";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AdminApi, type Fees } from "@/lib/admin/admin-api";

const WHOLE = new Intl.NumberFormat("en-NG");

const KINDS: { kind: keyof Fees; label: string }[] = [
  { kind: "electricity", label: "Electricity" },
  { kind: "tv", label: "TV" },
  { kind: "airtime", label: "Airtime" },
  { kind: "data", label: "Data" },
];

/** Stark's service fee per kind of bill, saved for the next payment with no deploy. */
export function AdminFees({ adminKey, fees }: { adminKey: string; fees: Fees }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Record<keyof Fees, string>>({
    electricity: String(fees.electricity),
    tv: String(fees.tv),
    airtime: String(fees.airtime),
    data: String(fees.data),
  });
  const save = useMutation({
    mutationFn: () =>
      AdminApi.updateFees(adminKey, {
        electricity: Number(draft.electricity),
        tv: Number(draft.tv),
        airtime: Number(draft.airtime),
        data: Number(draft.data),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "overview"] }),
  });
  const valid = KINDS.every(({ kind }) => /^\d+$/.test(draft[kind]));
  const changed = KINDS.some(({ kind }) => Number(draft[kind]) !== fees[kind]);

  return (
    <Card>
      <Eyebrow>Service fees</Eyebrow>
      <div className="grid gap-4 sm:grid-cols-4">
        {KINDS.map(({ kind, label }) => (
          <TextField
            key={kind}
            label={`${label} (₦)`}
            inputMode="numeric"
            value={/^\d+$/.test(draft[kind]) ? WHOLE.format(Number(draft[kind])) : draft[kind]}
            onChange={(event) =>
              setDraft({ ...draft, [kind]: event.target.value.replace(/[,\s]/g, "") })
            }
          />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => save.mutate()} disabled={!valid || !changed || save.isPending}>
          Save fees
        </Button>
        {save.isSuccess && !changed ? (
          <span className="text-sm text-muted-foreground">Saved. The next payment uses these.</span>
        ) : null}
        {save.error ? (
          <span className="text-sm text-destructive">
            {save.error instanceof ApiError ? save.error.message : "Couldn't save the fees."}
          </span>
        ) : null}
      </div>
    </Card>
  );
}
