import type { LinkCode } from "@stark/api/types";
import { TelegramDeepLink } from "@/components/connect/telegram-deep-link";

export function MintedCode({ minted }: { minted: LinkCode }) {
  return (
    <div
      aria-live="polite"
      className="flex flex-col items-start gap-2 rounded-lg bg-muted px-4 py-3"
    >
      <span className="text-sm text-fg-2">Send this to the bot</span>
      <span className="tabular font-mono text-2xl font-semibold tracking-widest">
        {minted.code}
      </span>
      <span className="text-xs text-muted-foreground">
        Expires in {Math.round(minted.expires_in / 60)} minutes.{" "}
        {minted.deep_link
          ? "One chat only, and /unlink ends it."
          : "Type it by hand — the server has no bot token, so there is no one-tap link."}
      </span>
      {minted.deep_link ? (
        <TelegramDeepLink href={minted.deep_link} botUsername={minted.bot_username} />
      ) : null}
    </div>
  );
}
