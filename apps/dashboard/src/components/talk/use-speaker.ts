import { api } from "@stark/api/client";
import { useRef } from "react";

/** Plays Stark's replies; `onFinished` runs once a clip ends (or never starts). */
export function useSpeaker(onFinished: () => void) {
  const player = useRef<HTMLAudioElement | null>(null);
  const speakSeq = useRef(0);
  const speaking = useRef(false);

  const stopSpeaking = () => {
    speaking.current = false;
    player.current?.pause();
    player.current = null;
  };

  const finishPlayback = (a: HTMLAudioElement) => {
    if (player.current !== a) return;
    player.current = null;
    speaking.current = false;
    onFinished();
  };

  /**
   * Fetches the voice after the words land, so text never waits on synthesis. The stream plays
   * first and the buffered clip is the fallback; a stale fetch never plays over a newer question.
   *
   * `url` is the ticket the turn already handed over: playing it skips a round trip, which was
   * 0.8s of silence between the words appearing and the first sound.
   */
  const speak = (text: string, url?: string | null) => {
    const seq = ++speakSeq.current;
    stopSpeaking();
    speaking.current = true;

    /** A stream refuses twice (once for the load, once for play()); one fetch. */
    let resolving = false;

    /**
     * Plays one clip. A refusal goes to `onRefuse` when given, so a refused stream hands off to the
     * buffered voice instead of reopening the mic mid-reply.
     */
    const play = (src: string, onRefuse?: (a: HTMLAudioElement) => void) => {
      const a = new Audio(src);
      player.current = a;
      const refuse = () => {
        if (player.current !== a) return;
        if (onRefuse) onRefuse(a);
        else finishPlayback(a);
      };
      a.addEventListener("ended", () => finishPlayback(a));
      a.addEventListener("error", refuse);
      void a.play().catch(refuse);
      return a;
    };

    /**
     * Fetches the whole clip after the stream refuses. If it never lands, the mic still comes back,
     * once.
     */
    const bufferedFallback = (a: HTMLAudioElement) => {
      if (resolving || seq !== speakSeq.current) return;
      resolving = true;
      api
        .speak(text)
        .then(({ audio }) => {
          if (seq !== speakSeq.current) return;
          if (!audio) return finishPlayback(a);
          if (player.current !== a) return;
          a.pause();
          player.current = null;
          speaking.current = true;
          play(audio);
        })
        .catch(() => {
          if (seq === speakSeq.current) finishPlayback(a);
        });
    };

    if (url) {
      play(api.streamUrl(url), bufferedFallback);
      return;
    }

    // `stopSpeaking` does not bump the sequence, so a ticket that lands after it must not play.
    api.speakStreamUrl(text).then(
      (src) => {
        if (seq === speakSeq.current && speaking.current) play(src, bufferedFallback);
      },
      () => {
        if (seq !== speakSeq.current || !speaking.current) return;
        speaking.current = false;
        onFinished();
      },
    );
  };

  return { speak, stopSpeaking, speaking };
}
