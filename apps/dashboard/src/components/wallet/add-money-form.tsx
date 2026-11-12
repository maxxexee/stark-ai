import { errorCopy } from "@stark/api/errors";
import { useStartDeposit, useTopUp } from "@stark/api/mutations";
import { cryptoAssetsQuery, depositPreviewQuery, usdcRatesQuery } from "@stark/api/queries";
import type { Deposit, DepositPreviewInput, FundingMethods } from "@stark/api/types";
import { Button } from "@stark/ui/components/button";
import { FieldError } from "@stark/ui/components/field";
import { Spinner } from "@stark/ui/components/spinner";
import { formatAmountInput, formatNaira, parseAmountInput } from "@stark/utils/format";
import { requestId } from "@stark/utils/id";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown as ArrowDownIcon } from "reicon-react";
import { SendCurrencyPicker } from "@/components/wallet/send-currency-picker";
import { SwapPanel } from "@/components/wallet/swap-panel";
import { TestMoneyNote } from "@/components/wallet/test-money-note";
import { useDebouncedValue } from "@/components/wallet/use-debounced-value";
import { type SendOption, SendOptions } from "@/lib/wallet/send-options";

const MIN_NGN = 100;

/** What the card was filled with, kept in the URL so going back to it restores it. */
export type AddMoneyChoice = { amount: number; option: string | undefined };

type Typed = { side: "send" | "receive"; value: string };

/**
 * For crypto either side can be typed: the other fills from a dry quote once typing settles. Send
 * is focused on arrival only with a fine pointer, since on a phone it would raise the keyboard
 * before the page is read.
 */
export function AddMoneyForm({
  methods,
  initial,
  onStarted,
  onTestMoneyAdded,
}: {
  methods: FundingMethods;
  initial: AddMoneyChoice;
  onStarted: (deposit: Deposit, choice: AddMoneyChoice) => void;
  onTestMoneyAdded: () => void;
}) {
  const assets = useQuery({ ...cryptoAssetsQuery(), enabled: methods.crypto });
  const groups = SendOptions.groups(methods, assets.data ?? []);
  const [pickedKey, setPickedKey] = useState(initial.option);
  const option =
    groups.flatMap((group) => group.items).find((o) => SendOptions.key(o) === pickedKey) ??
    groups[0]?.items[0] ??
    null;
  const [typed, setTyped] = useState<Typed>({
    side: "receive",
    value: String(initial.amount),
  });
  const settled = useDebouncedValue(typed, 400);
  const sendPanel = useRef<HTMLDivElement>(null);
  const sendInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (window.matchMedia("(pointer: fine)").matches) sendInput.current?.select();
  }, []);

  const crypto = option?.kind === "crypto" ? option.asset : null;
  const previewInput: DepositPreviewInput | null =
    crypto && Number(settled.value) > 0
      ? settled.side === "receive"
        ? { asset_id: crypto.asset_id, amount_ngn: Number(settled.value) }
        : { asset_id: crypto.asset_id, amount_in: settled.value }
      : null;
  const preview = useQuery(depositPreviewQuery(previewInput));
  const rates = useQuery({ ...usdcRatesQuery(), enabled: crypto !== null });
  const start = useStartDeposit();
  const topUp = useTopUp();

  const settling = typed !== settled || preview.isFetching;
  const receiveNgn =
    crypto && typed.side === "send" ? (preview.data?.amount_ngn ?? 0) : Number(typed.value);
  const topUpKey = useMemo(() => requestId("dep"), [receiveNgn]);

  if (!option) {
    return <p className="m-0 text-fg-2">Adding money isn’t switched on here yet.</p>;
  }

  const sendValue = crypto
    ? typed.side === "send"
      ? typed.value
      : (preview.data?.amount_in ?? "")
    : formatAmountInput(Number(typed.value));
  const receiveValue = formatAmountInput(receiveNgn);

  const handleSendChange = (raw: string) => {
    if (!crypto)
      return setTyped({
        side: "receive",
        value: String(parseAmountInput(raw)),
      });
    const decimal = raw.replace(/[^0-9.]/g, "").replace(/(\..*)\./g, "$1");
    setTyped({ side: "send", value: decimal });
  };

  const handleReceiveChange = (raw: string) =>
    setTyped({ side: "receive", value: String(parseAmountInput(raw)) });

  const handleOptionChange = (next: SendOption) => {
    if (typed.side === "send") setTyped({ side: "receive", value: String(receiveNgn) });
    setPickedKey(SendOptions.key(next));
  };

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (ready) handleContinue();
  };

  const handleContinue = () => {
    if (option.kind === "test")
      return topUp.mutate(
        { amount_ngn: receiveNgn, request_id: topUpKey },
        { onSuccess: onTestMoneyAdded },
      );
    const input = crypto
      ? {
          method: "crypto" as const,
          amount_ngn: receiveNgn,
          asset_id: crypto.asset_id,
        }
      : { method: "bank" as const, amount_ngn: receiveNgn };
    start.mutate(input, {
      onSuccess: (deposit) =>
        onStarted(deposit, { amount: receiveNgn, option: SendOptions.key(option) }),
    });
  };

  const busy = start.isPending || topUp.isPending;
  const error = preview.error ?? start.error ?? topUp.error;
  const ready =
    receiveNgn >= MIN_NGN && !busy && (!crypto || (preview.data !== undefined && !settling));

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-6">
      <div className="relative flex flex-col gap-1 rounded-card bg-surface-2 p-1">
        <SwapPanel
          ref={sendPanel}
          inputRef={sendInput}
          label="Send"
          value={sendValue}
          onChange={handleSendChange}
          inputMode={crypto ? "decimal" : "numeric"}
          pending={crypto !== null && typed.side === "receive" && settling}
          currency={
            <SendCurrencyPicker
              groups={groups}
              value={option}
              onChange={handleOptionChange}
              anchor={sendPanel}
              returnFocusTo={sendInput}
            />
          }
        />
        <span
          aria-hidden="true"
          className="absolute top-1/2 left-1/2 flex size-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-lg border-4 border-surface-2 bg-card text-muted-foreground"
        >
          <ArrowDownIcon className="size-4" />
        </span>
        <SwapPanel
          label="Receive in your Stark balance"
          value={receiveValue}
          onChange={handleReceiveChange}
          inputMode="numeric"
          pending={crypto !== null && typed.side === "send" && settling}
          currency={
            <span className="flex h-9 shrink-0 items-center rounded-lg bg-surface-2 px-3 text-base font-medium text-fg">
              NGN
            </span>
          }
        />
      </div>

      {crypto && rates.data ? (
        <p className="m-0 text-sm text-fg-2">
          1 USDC = {formatNaira(Number(rates.data.deposit))}. The exact amount to send locks when
          you continue.
        </p>
      ) : null}
      {option.kind === "test" ? <TestMoneyNote /> : null}
      {error ? <FieldError className="text-sm">{errorCopy(error)}</FieldError> : null}

      <Button type="submit" size="lg" block disabled={!ready}>
        {busy ? <Spinner /> : null}
        {option.kind === "test"
          ? `Add ${formatNaira(receiveNgn)} test money`
          : crypto
            ? `Pay with ${crypto.symbol}`
            : `Pay ${formatNaira(receiveNgn)}`}
      </Button>
    </form>
  );
}
