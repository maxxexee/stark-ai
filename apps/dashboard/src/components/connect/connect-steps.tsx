export function ConnectSteps({ minted }: { minted: boolean }) {
  return (
    <ol className="m-0 flex list-decimal flex-col gap-1.5 pl-5 text-sm text-fg-2">
      <li>
        Get a code. It is single-use and lasts {minted ? "ten minutes" : "10 minutes"}, and getting
        another cancels it.
      </li>
      <li>
        Open Telegram and tap the link, or send <span className="font-mono">link 482913</span> (your
        own six digits) to the bot.
      </li>
      <li>Then just talk to it: “how much is left”, “pay 5000 for electricity”.</li>
    </ol>
  );
}
