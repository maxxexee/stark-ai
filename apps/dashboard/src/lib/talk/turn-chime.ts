/**
 * A short two-tone blip when a turn starts, so the room hears something at once.
 *
 * The wait for an answer runs from about a second to several, and in hands-free mode those seconds
 * were pure silence: the screen says "One moment" but nobody in the room looks at the screen. Made
 * with the Web Audio API rather than a sound file, so it starts on the same tick as the tap and
 * nothing has to download first.
 */

let context: AudioContext | null = null;

function audioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  context ??= new Ctor();
  return context;
}

/** Best effort: a refused or suspended context is silence, never an error. */
export function turnChime() {
  try {
    const ctx = audioContext();
    if (!ctx) return;
    void ctx.resume().catch(() => {});
    const at = ctx.currentTime;
    [660, 880].forEach((hz, index) => {
      const start = at + index * 0.085;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = hz;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.05, start + 0.012);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.07);
      osc.connect(gain).connect(ctx.destination);
      osc.start(start);
      osc.stop(start + 0.075);
    });
  } catch {
    // No audio is still better than a broken turn.
  }
}
