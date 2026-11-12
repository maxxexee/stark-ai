/**
 * Writes a Content-Security-Policy `<meta>` into every built HTML page.
 *
 * The session token lives in localStorage, so a script injected into this origin could read it.
 * The policy lets scripts run only from this origin or as the exact inline scripts TanStack
 * prerendered into the shell (allowed by hash, so no `'unsafe-inline'`), and lets the page talk only
 * to itself, the API and Neon Auth.
 *
 * Run after `vite build`, because the shell's inline scripts exist only once it is prerendered.
 * A `<meta>` cannot carry `frame-ancestors`: the static host must send that as a header.
 */
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { loadEnv } from "vite";

class ContentSecurityPolicy {
  private static readonly INLINE_SCRIPT = /<script(?![^>]*\ssrc=)[^>]*>([\s\S]*?)<\/script>/g;

  constructor(
    private readonly apiOrigin: string,
    private readonly authOrigin: string,
  ) {}

  /** The policy for one page: its own inline scripts are the only ones it may run. */
  forPage(html: string): string {
    // The body group always participates (it may be empty), so it is always a string.
    const hashes = [...html.matchAll(ContentSecurityPolicy.INLINE_SCRIPT)].map(
      ([, body]) =>
        `'sha256-${createHash("sha256")
          .update(body as string)
          .digest("base64")}'`,
    );
    return [
      "default-src 'self'",
      `script-src 'self' ${hashes.join(" ")}`,
      // React and Tailwind set style attributes; a style cannot read localStorage.
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob:",
      "font-src 'self' data:",
      // The buffered voice is a data: URL; the streamed one comes from the API.
      `media-src 'self' data: blob: ${this.apiOrigin}`,
      `connect-src 'self' ${this.apiOrigin} ${this.authOrigin}`,
      "object-src 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ]
      .join("; ")
      .replace(/\s+;/g, ";");
  }

  apply(html: string): string {
    const meta = `<meta http-equiv="Content-Security-Policy" content="${this.forPage(html)}">`;
    return html.replace("<head>", `<head>${meta}`);
  }
}

const appDir = fileURLToPath(new URL("..", import.meta.url));
const distDir = `${appDir}dist/client/`;
const env = loadEnv("production", appDir, "VITE_");
// Empty in a same-origin build (the proxy), where 'self' already covers the API.
const origin = (url: string | undefined) => (url ? new URL(url).origin : "");

const policy = new ContentSecurityPolicy(
  origin(env.VITE_STARK_API_URL),
  origin(env.VITE_NEON_AUTH_URL),
);
const pages = readdirSync(distDir).filter((name) => name.endsWith(".html"));
if (pages.length === 0) throw new Error(`No HTML in ${distDir}: run vite build first.`);
for (const page of pages) {
  const path = `${distDir}${page}`;
  writeFileSync(path, policy.apply(readFileSync(path, "utf8")));
}
console.log(`Content-Security-Policy written into ${pages.join(", ")}`);
