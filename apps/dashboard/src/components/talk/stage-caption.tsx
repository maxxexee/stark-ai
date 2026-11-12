import { errorCopy } from "@stark/api/errors";
import type { Stage } from "@/lib/talk/types";

export function StageCaption({
  stage,
  canListen,
  session,
  error,
  notice,
}: {
  stage: Stage;
  canListen: boolean;
  session: boolean;
  error: Error | null;
  notice: string | null;
}) {
  const copy = {
    idle: [
      "Tap and speak",
      canListen ? "Start with “Hey Stark”, then say what you need." : "Type what you need below.",
    ],
    listening: [
      "Listening…",
      session
        ? "Keep going — you only say Stark once."
        : "Start with “Hey Stark”, then say what you need.",
    ],
    thinking: ["One moment", "Checking your bills and balance."],
    done: error
      ? ["Couldn’t reach Stark", errorCopy(error)]
      : session
        ? ["Still listening", "Say your next question whenever."]
        : ["Done", "Here’s what Stark said."],
  }[stage];

  return (
    <div
      key={stage}
      className="flex min-h-16 flex-col gap-1.5 animate-in fade-in slide-in-from-bottom-2 duration-300"
    >
      <span className="text-2xl font-semibold tracking-tight lg:text-3xl">{copy[0]}</span>
      <span className="text-sm text-muted-foreground lg:text-base">{copy[1]}</span>
      {notice ? <span className="text-sm text-brand-warm">{notice}</span> : null}
    </div>
  );
}
