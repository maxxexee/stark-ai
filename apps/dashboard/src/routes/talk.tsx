import { stateQuery } from "@stark/api/queries";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";
import { SpendNote } from "@/components/talk/spend-note";
import { StageCaption } from "@/components/talk/stage-caption";
import { StatusCards } from "@/components/talk/status-cards";
import { TalkGlow } from "@/components/talk/talk-glow";
import { TalkHeader } from "@/components/talk/talk-header";
import { TranscriptCard } from "@/components/talk/transcript-card";
import { TypeForm } from "@/components/talk/type-form";
import { useVoiceSession } from "@/components/talk/use-voice-session";
import { VoiceOrb } from "@/components/talk/voice-orb";

export const Route = createFileRoute("/talk")({
  validateSearch: z.object({ q: z.string().optional() }),
  head: () => ({ meta: [{ title: "Talk · Stark" }] }),
  component: Talk,
});

function Talk() {
  const { q } = Route.useSearch();
  const { data: state } = useQuery(stateQuery());
  const talk = useVoiceSession(q);

  const live = talk.stage === "listening" || talk.stage === "thinking";

  return (
    <div className="talk-scope dark relative flex min-h-dvh flex-col gap-6 overflow-hidden bg-canvas px-4 pt-6 pb-8 text-fg sm:px-10 lg:gap-0 lg:px-16">
      <TalkGlow live={live} />
      <TalkHeader />

      <div className="relative mx-auto flex w-full max-w-120 flex-1 flex-col gap-5 lg:grid lg:max-w-6xl lg:grid-cols-[1fr_minmax(0,440px)] lg:items-center lg:gap-16 lg:py-10">
        <div className="flex flex-1 flex-col items-center justify-center gap-6 text-center lg:gap-8">
          <VoiceOrb stage={talk.stage} live={live} onTap={talk.handleMicrophoneTap} />
          <StageCaption
            stage={talk.stage}
            canListen={talk.canListen}
            session={talk.session}
            error={talk.error}
            notice={talk.notice}
          />
        </div>

        <div className="contents lg:flex lg:flex-col lg:gap-5">
          {state ? <StatusCards state={state} /> : null}
          <TranscriptCard stage={talk.stage} reply={talk.reply} heard={talk.heard} />
          <TypeForm thinking={talk.stage === "thinking"} onSend={talk.handleTypedMessage} />
          <SpendNote />
        </div>
      </div>
    </div>
  );
}
