type RecognitionResult = { 0: { transcript: string }; isFinal: boolean };
type RecognitionEvent = { results: ArrayLike<RecognitionResult> };

export type Recognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: RecognitionEvent) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error?: string }) => void) | null;
  start: () => void;
  stop: () => void;
};

export class SpeechRecognizer {
  static create(): Recognition | null {
    if (typeof window === "undefined") return null;
    const w = window as unknown as {
      SpeechRecognition?: new () => Recognition;
      webkitSpeechRecognition?: new () => Recognition;
    };
    const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!Ctor) return null;
    const r = new Ctor();
    r.lang = "en-NG";
    r.interimResults = true;
    r.continuous = false;
    return r;
  }

  static transcript(e: RecognitionEvent): string {
    return Array.from(e.results, (r) => r[0].transcript).join(" ");
  }
}
