import { useVoice, useVoiceAudio } from "@stark/api/mutations";
import type { VoiceReply } from "@stark/api/types";
import { useEffect, useRef, useState } from "react";
import { useClipRecorder } from "@/components/talk/use-clip-recorder";
import { useSpeaker } from "@/components/talk/use-speaker";
import { SleepIntent } from "@/lib/speech/sleep-intent";
import type { Recognition } from "@/lib/speech/speech-recognizer";
import { SpeechRecognizer } from "@/lib/speech/speech-recognizer";
import { AudioRecording } from "@/lib/talk/audio-recording";
import { MicErrors } from "@/lib/talk/mic-errors";
import { StarkAddress } from "@/lib/talk/stark-address";
import type { Stage } from "@/lib/talk/types";

const RESTART_MS = 350;

/**
 * The hands-free voice loop: wake on a tap, hear, answer, keep listening until told to sleep. A
 * hidden tab ends the session, because browsers throttle or kill the recognizer there.
 */
export function useVoiceSession(q: string | undefined) {
  const voice = useVoice();
  const voiceAudio = useVoiceAudio();
  const [stage, setStage] = useState<Stage>("idle");
  const [heard, setHeard] = useState("");
  const [reply, setReply] = useState<VoiceReply | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [session, setSession] = useState(false);
  const [canListen, setCanListen] = useState(false);
  const recognition = useRef<Recognition | null>(null);
  const sentQ = useRef(false);

  const stageRef = useRef<Stage>("idle");
  const awake = useRef(false);
  const restartTimer = useRef<number | null>(null);
  const micWanted = useRef(false);
  const stopRequested = useRef(false);
  const fatalError = useRef(false);

  const { speak, stopSpeaking, speaking } = useSpeaker(() => scheduleRestart());
  const clips = useClipRecorder();

  const go = (next: Stage) => {
    stageRef.current = next;
    setStage(next);
  };

  const inSession = () => awake.current;

  const endSession = () => {
    awake.current = false;
    micWanted.current = false;
    if (restartTimer.current !== null) {
      window.clearTimeout(restartTimer.current);
      restartTimer.current = null;
    }
    const r = recognition.current;
    recognition.current = null;
    stopRequested.current = false;
    try {
      r?.stop();
    } catch {}
    setSession(false);
  };

  const closeIdle = () => {
    endSession();
    go("idle");
  };

  const scheduleRestart = () => {
    if (restartTimer.current !== null || !micWanted.current) return;
    restartTimer.current = window.setTimeout(() => {
      restartTimer.current = null;
      listen();
    }, RESTART_MS);
  };

  const recordThenSend = () => {
    clips.record({
      onStart: () => go("listening"),
      onClip: (blob) => {
        if (blob.size < 1024) {
          closeIdle();
          setNotice("I didn't hear that. Tap and try again, or type below.");
          return;
        }
        go("thinking");
        voiceAudio.mutate(blob, {
          onSuccess: (res) => {
            if (res.ignored) {
              if (import.meta.env.DEV) {
                console.debug("[wake] ignored (audio):", res.transcript);
              }
              closeIdle();
              setNotice(
                "Start with “Hey Stark” — then say what you need; typos and accents are fine.",
              );
              return;
            }
            if (SleepIntent.matches(res.transcript)) {
              endSession();
              go("idle");
              setHeard(res.transcript);
              setNotice("Asleep. Tap the mic when you need me.");
              speak("Okay. I'll be here — tap the mic when you need me.");
              return;
            }
            setHeard(res.transcript);
            setReply(res);
            go("done");
            if (res.reply) speak(res.reply);
            else scheduleRestart();
          },
          onError: () => {
            go("done");
            scheduleRestart();
          },
        });
      },
      onDenied: () => {
        closeIdle();
        setNotice(MicErrors.copy("not-allowed"));
      },
    });
  };

  const submit = (said: string, opts: { address?: boolean } = {}) => {
    if (SleepIntent.matches(said)) {
      endSession();
      go("idle");
      setHeard(said);
      setNotice("Asleep. Tap the mic when you need me.");
      speak("Okay. I'll be here — tap the mic when you need me.");
      return;
    }
    stopSpeaking();
    setNotice(null);
    setReply(null);
    go("thinking");
    const transcript = opts.address || inSession() ? StarkAddress.apply(said) : said;
    voice.mutate(transcript, {
      onSuccess: (res) => {
        if (res.ignored) {
          if (import.meta.env.DEV) console.debug("[wake] ignored:", said);
          closeIdle();
          setNotice("Start with “Hey Stark” — then say what you need; typos and accents are fine.");
          return;
        }
        setReply(res);
        go("done");
        if (res.reply) speak(res.reply);
        else scheduleRestart();
      },
      onError: () => {
        go("done");
        scheduleRestart();
      },
    });
  };

  /**
   * One utterance: speech is sent, silence keeps listening, a stop request or an error sleeps.
   * Chrome refuses a start that races the previous stop (InvalidStateError), so that failure is
   * reported instead of sleeping silently.
   */
  const listen = () => {
    if (recognition.current) return;
    if (stageRef.current === "thinking" || speaking.current) return;
    if (!micWanted.current || !awake.current) {
      go("idle");
      return;
    }
    const r = SpeechRecognizer.create();
    if (!r) {
      if (AudioRecording.supported()) {
        recordThenSend();
        return;
      }
      micWanted.current = false;
      go("idle");
      setNotice("This browser can’t listen — type what you need below.");
      document.getElementById("type-instead")?.focus();
      return;
    }

    fatalError.current = false;
    stopRequested.current = false;
    recognition.current = r;
    let text = "";

    r.onresult = (e) => {
      text = SpeechRecognizer.transcript(e);
      setHeard(text);
    };

    r.onerror = (e) => {
      const error = e.error;
      if (error === "no-speech" || error === "aborted") return;
      fatalError.current = true;
      closeIdle();
      setNotice(MicErrors.copy(error));
    };

    r.onend = () => {
      if (recognition.current !== r) return;
      recognition.current = null;
      const said = text.trim();
      if (said) {
        submit(said);
        return;
      }
      if (stopRequested.current) {
        closeIdle();
        return;
      }
      if (fatalError.current) return;
      if (!micWanted.current || !awake.current) {
        closeIdle();
        setNotice("I didn’t hear that. Tap and try again, or type below.");
        return;
      }
      scheduleRestart();
    };

    go("listening");
    try {
      r.start();
    } catch {
      recognition.current = null;
      go("idle");
      setNotice("The mic didn’t restart — tap the orb, or type below.");
      closeIdle();
    }
  };

  const handleMicrophoneTap = () => {
    if (stageRef.current === "listening") {
      if (clips.recording()) {
        clips.stop();
        return;
      }
      stopRequested.current = true;
      recognition.current?.stop();
      return;
    }
    stopSpeaking();
    setNotice(null);
    if (!canListen) {
      document.getElementById("type-instead")?.focus();
      return;
    }
    micWanted.current = true;
    awake.current = true;
    setSession(true);
    listen();
  };

  const handleTypedMessage = (text: string) => {
    setHeard(text);
    setReply(null);
    submit(text, { address: true });
  };

  useEffect(
    () => () => {
      endSession();
      stopSpeaking();
      clips.dispose();
    },
    [],
  );

  useEffect(
    () => setCanListen(SpeechRecognizer.create() !== null || AudioRecording.supported()),
    [],
  );

  useEffect(() => {
    const handleTabHidden = () => {
      if (document.visibilityState !== "hidden" || !awake.current) return;
      endSession();
      go("idle");
      setNotice("Asleep — the mic stops while this tab is hidden. Tap to wake me.");
    };
    document.addEventListener("visibilitychange", handleTabHidden);
    return () => document.removeEventListener("visibilitychange", handleTabHidden);
  }, []);

  useEffect(() => {
    if (q && !sentQ.current) {
      sentQ.current = true;
      setHeard(q);
      submit(q, { address: true });
    }
  }, [q]);

  return {
    stage,
    heard,
    reply,
    notice,
    session,
    canListen,
    error: voice.error ?? voiceAudio.error,
    handleMicrophoneTap,
    handleTypedMessage,
  };
}
