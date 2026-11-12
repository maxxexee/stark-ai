import { Button } from "@stark/ui/components/button";
import { Card } from "@stark/ui/components/card";
import { Eyebrow } from "@stark/ui/components/eyebrow";
import { Spinner } from "@stark/ui/components/spinner";
import { useEffect, useState } from "react";

const WINDOW_SECONDS = 10 * 60;

/**
 * After "I've sent it": a ten-minute countdown while Stark watches for the transfer. It is
 * a guide, not a deadline: when it runs out Stark keeps checking, and the deposit's own
 * window decides when an unpaid one expires.
 */
export function CryptoDepositWait({
  since,
  seen,
  asset,
  onShowAddress,
}: {
  since: number;
  seen: boolean;
  asset: string;
  onShowAddress: () => void;
}) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const left = Math.max(0, WINDOW_SECONDS - Math.floor((now - since) / 1000));
  const clock = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;

  return (
    <Card className="gap-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <Eyebrow>{seen ? "Received" : "Waiting for your transfer"}</Eyebrow>
          <span className="font-medium">
            {seen ? `Swapping your ${asset} to naira` : `Looking for your ${asset}`}
          </span>
        </div>
        <Spinner />
      </div>
      <div className="flex flex-col gap-2">
        <div
          role="progressbar"
          aria-label="Time left in the usual window"
          aria-valuemin={0}
          aria-valuemax={WINDOW_SECONDS}
          aria-valuenow={left}
          className="h-1 w-full overflow-hidden rounded-full bg-track"
        >
          <div
            className="h-full rounded-full bg-brand transition-[width] duration-1000 ease-linear"
            style={{ width: `${(left / WINDOW_SECONDS) * 100}%` }}
          />
        </div>
        <p className="m-0 text-sm text-fg-2">
          {left > 0
            ? `Usually done within ${clock}. You can leave this page: it lands in your balance on its own.`
            : "Taking longer than usual. Stark keeps checking, so you can leave this page."}
        </p>
      </div>
      {seen ? null : (
        <Button variant="secondary" block onClick={onShowAddress}>
          Show the address again
        </Button>
      )}
    </Card>
  );
}
