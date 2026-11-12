import { ApiError } from "@stark/api/errors";
import { Button } from "@stark/ui/components/button";
import { Card } from "@stark/ui/components/card";
import { Eyebrow } from "@stark/ui/components/eyebrow";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AdminLimitField } from "@/components/admin/admin-limit-field";
import { AdminApi, type OperatorLimit } from "@/lib/admin/admin-api";

const GROUPS: { title: string; keys: string[] }[] = [
  {
    title: "Withdrawals",
    keys: [
      "withdraw_daily_ngn",
      "bank_lookups_per_day",
      "crypto_withdraw_max_ngn",
      "crypto_withdraw_max_usdc",
      "crypto_withdraw_daily_ngn",
      "crypto_withdraw_user_daily_ngn",
      "card_hold_hours",
    ],
  },
  {
    title: "Rate",
    keys: [
      "usdc_rate_min",
      "usdc_rate_max",
      "usdc_rate_max_move_pct",
      "usdc_spread_ngn",
      "usdc_rate_pinned",
    ],
  },
  { title: "Alerts", keys: ["float_low_ngn", "treasury_low_usdc"] },
  { title: "Rate limits", keys: ["speak_per_minute", "telemetry_per_minute"] },
];

/** The value typed for a limit, or null when it is not a whole number in its range. */
function parse(limit: OperatorLimit, text: string): number | null {
  if (!/^\d+$/.test(text)) return null;
  const value = Number(text);
  return value >= limit.minimum && value <= limit.maximum ? value : null;
}

/** Every operator limit, saved to the API and applied within seconds with no deploy. */
export function AdminLimits({ adminKey, limits }: { adminKey: string; limits: OperatorLimit[] }) {
  const queryClient = useQueryClient();
  // Only what the owner has typed; every other field shows the saved value.
  const [draft, setDraft] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: (changes: Record<string, number | null>) =>
      AdminApi.updateLimits(adminKey, changes),
    onSuccess: async (_saved, changes) => {
      // Wait for the fresh overview, so a cleared field never shows the old value.
      await queryClient.invalidateQueries({ queryKey: ["admin", "overview"] });
      setDraft((current) =>
        Object.fromEntries(Object.entries(current).filter(([key]) => !(key in changes))),
      );
    },
  });

  const text = (limit: OperatorLimit) => draft[limit.key] ?? String(limit.value);
  const edited = limits.filter((limit) => text(limit) !== String(limit.value));
  const valid = edited.every((limit) => parse(limit, text(limit)) !== null);

  // A limit the API added after this page was built still shows, under its own heading.
  const grouped = new Set(GROUPS.flatMap((group) => group.keys));
  const sections = [
    ...GROUPS.map((group) => ({
      title: group.title,
      limits: limits.filter((limit) => group.keys.includes(limit.key)),
    })),
    { title: "Other", limits: limits.filter((limit) => !grouped.has(limit.key)) },
  ].filter((section) => section.limits.length > 0);

  return (
    <Card>
      <Eyebrow>Limits</Eyebrow>
      {sections.map((section) => (
        <section key={section.title} className="flex flex-col gap-3">
          <h3 className="m-0 text-sm font-semibold text-fg-2">{section.title}</h3>
          <div className="grid gap-4 sm:grid-cols-2">
            {section.limits.map((limit) => (
              <AdminLimitField
                key={limit.key}
                limit={limit}
                text={text(limit)}
                invalid={edited.includes(limit) && parse(limit, text(limit)) === null}
                disabled={save.isPending}
                onChange={(value) => setDraft({ ...draft, [limit.key]: value })}
                onReset={() => save.mutate({ [limit.key]: null })}
              />
            ))}
          </div>
        </section>
      ))}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          onClick={() =>
            save.mutate(Object.fromEntries(edited.map((limit) => [limit.key, Number(text(limit))])))
          }
          disabled={edited.length === 0 || !valid || save.isPending}
        >
          Save limits
        </Button>
        {save.isSuccess && edited.length === 0 ? (
          <span className="text-sm text-muted-foreground">Saved. Applies within seconds.</span>
        ) : null}
        {save.error ? (
          <span className="text-sm text-destructive">
            {save.error instanceof ApiError ? save.error.message : "Couldn't save the limits."}
          </span>
        ) : null}
      </div>
    </Card>
  );
}
