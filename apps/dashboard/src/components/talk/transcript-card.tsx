import type { VoiceReply } from "@stark/api/types";
import { Card } from "@stark/ui/components/card";
import { cn } from "@stark/ui/utils/cn";
import { DepositReply } from "@/components/talk/deposit-reply";
import { HeardLines } from "@/components/talk/heard-lines";
import { ReplyLines } from "@/components/talk/reply-lines";
import { TryLines } from "@/components/talk/try-lines";
import type { Stage } from "@/lib/talk/types";

export function TranscriptCard({
  stage,
  reply,
  heard,
}: {
  stage: Stage;
  reply: VoiceReply | null;
  heard: string;
}) {
  return (
    <Card
      aria-live="polite"
      className={cn("min-h-30 gap-2 lg:min-h-48", stage === "thinking" && "voice-scan")}
    >
      {reply?.reply ? (
        <>
          <ReplyLines reply={reply.reply} token={reply.token} />
          {reply.deposit ? <DepositReply deposit={reply.deposit} /> : null}
        </>
      ) : heard ? (
        <HeardLines heard={heard} />
      ) : (
        <TryLines />
      )}
    </Card>
  );
}
