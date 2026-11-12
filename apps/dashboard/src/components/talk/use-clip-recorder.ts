import { useRef } from "react";

const RECORD_MS = 8_000;

/** Records one clip from the mic for server-side hearing, where the browser has no recognizer. */
export function useClipRecorder() {
  const recorder = useRef<MediaRecorder | null>(null);
  const recordStop = useRef<number | null>(null);
  const disposed = useRef(false);

  const stop = () => {
    if (recordStop.current !== null) {
      window.clearTimeout(recordStop.current);
      recordStop.current = null;
    }
    const rec = recorder.current;
    recorder.current = null;
    if (rec && rec.state !== "inactive") {
      try {
        rec.stop();
      } catch {}
    }
  };

  const record = (handlers: {
    onStart: () => void;
    onClip: (blob: Blob) => void;
    onDenied: () => void;
  }) => {
    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then((stream) => {
        const rec = new MediaRecorder(stream);
        const parts: BlobPart[] = [];
        rec.ondataavailable = (e) => {
          if (e.data.size) parts.push(e.data);
        };
        rec.onstop = () => {
          if (recordStop.current !== null) {
            window.clearTimeout(recordStop.current);
            recordStop.current = null;
          }
          recorder.current = null;
          stream.getTracks().forEach((t) => {
            t.stop();
          });
          if (disposed.current) return;
          handlers.onClip(new Blob(parts, { type: rec.mimeType || "audio/webm" }));
        };
        recorder.current = rec;
        rec.start();
        handlers.onStart();
        recordStop.current = window.setTimeout(() => {
          recordStop.current = null;
          if (rec.state !== "inactive") rec.stop();
        }, RECORD_MS);
      })
      .catch(() => handlers.onDenied());
  };

  const recording = () => recorder.current !== null;

  /** Unmount: a clip still in flight is dropped, never sent. */
  const dispose = () => {
    disposed.current = true;
    if (recordStop.current !== null) window.clearTimeout(recordStop.current);
    const rec = recorder.current;
    recorder.current = null;
    if (rec && rec.state !== "inactive") {
      try {
        rec.stop();
      } catch {}
    }
  };

  return { record, stop, recording, dispose };
}
