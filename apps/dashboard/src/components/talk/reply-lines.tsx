import { formatToken } from "@stark/utils/format";
import { VoiceLine } from "@/components/talk/voice-line";

export function ReplyLines({ reply, token }: { reply: string; token: string | null }) {
  return (
    <>
      <VoiceLine key={`who-${reply}`} delay="0ms" className="text-xs text-muted-foreground">
        Stark
      </VoiceLine>
      <VoiceLine key={reply} delay="60ms">
        {reply}
      </VoiceLine>
      {token ? (
        <VoiceLine key={token} delay="140ms" className="tabular text-lg font-medium">
          {formatToken(token)}
        </VoiceLine>
      ) : null}
    </>
  );
}
