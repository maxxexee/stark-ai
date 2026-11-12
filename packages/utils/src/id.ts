/**
 * Repeating the same id returns the original entry instead of charging twice, so create one per
 * user intent, not per request.
 */
export function requestId(prefix: string): string {
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${prefix}_${hex}`;
}
