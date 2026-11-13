import { ApiError } from "./errors";
import type {
  ApprovedPayment,
  Bank,
  BankAccount,
  Bill,
  BillKind,
  BillPatch,
  Controls,
  CryptoAsset,
  CryptoWithdrawInput,
  DemoSnapshot,
  Deposit,
  DepositPreview,
  DepositPreviewInput,
  FundingMethods,
  Limits,
  LimitsPatch,
  LinkCode,
  LinkedChat,
  NewBill,
  Payee,
  PaymentInput,
  PaymentRequest,
  Plan,
  Receipt,
  ResolvedAccount,
  SpeakReply,
  SpeakTicket,
  StartDeposit,
  State,
  Suggestion,
  TopUpInput,
  UsdcRates,
  VoiceReply,
  Wallet,
  WalletMovement,
  Withdrawal,
  WithdrawInput,
} from "./types";

let baseUrl = "";
let authToken: string | null = null;

/**
 * Leave it empty for browser development, where Vite proxies `/v1` to the backend; set it for
 * deployed builds.
 */
export function setApiBaseUrl(url: string) {
  baseUrl = url.replace(/\/$/, "");
}

/**
 * Held in memory rather than read from storage per request, so a signed-out tab cannot keep working
 * off a token left in localStorage.
 */
export function setAuthToken(token: string | null) {
  authToken = token;
}

/** A recorded clip as base64, chunked so a long utterance cannot blow the stack. */
async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (authToken) headers.Authorization = `Bearer ${authToken}`;
    res = await fetch(`${baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "Network request failed");
  }

  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(
      res.status,
      data?.code ?? "unknown",
      data?.message ?? res.statusText,
      data?.detail ?? {},
    );
  }
  return data as T;
}

export const api = {
  state: () => request<State>("GET", "/v1/state"),
  bills: () => request<Bill[]>("GET", "/v1/bills"),
  bill: (id: string) => request<Bill>("GET", `/v1/bills/${encodeURIComponent(id)}`),
  addBill: (input: NewBill) => request<Bill>("POST", "/v1/bills", input),
  updateBill: (id: string, patch: BillPatch) =>
    request<Bill>("PATCH", `/v1/bills/${encodeURIComponent(id)}`, patch),
  confirmBill: (id: string) => request<Bill>("POST", `/v1/bills/${encodeURIComponent(id)}/confirm`),
  deleteBill: (id: string) =>
    request<{ deleted: true; bill_id: string }>("DELETE", `/v1/bills/${encodeURIComponent(id)}`),
  plans: (params: { kind?: Extract<BillKind, "data" | "tv">; provider?: string } = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter((e): e is [string, string] => Boolean(e[1])),
    );
    return request<Plan[]>("GET", `/v1/plans${qs.size ? `?${qs}` : ""}`);
  },
  pay: (input: PaymentInput) => request<Receipt>("POST", "/v1/payments", input),
  activity: () => request<Receipt[]>("GET", "/v1/activity"),
  limits: () => request<Limits>("GET", "/v1/limits"),
  updateLimits: (patch: LimitsPatch) => request<Limits>("PATCH", "/v1/limits", patch),
  wallet: () => request<Wallet>("GET", "/v1/wallet"),
  topUp: (input: TopUpInput) => request<WalletMovement>("POST", "/v1/wallet/topup", input),
  fundingMethods: () => request<FundingMethods>("GET", "/v1/wallet/methods"),
  cryptoAssets: () => request<CryptoAsset[]>("GET", "/v1/wallet/crypto-assets"),
  usdcRates: () => request<UsdcRates>("GET", "/v1/wallet/rates"),
  previewDeposit: (input: DepositPreviewInput) =>
    request<DepositPreview>("POST", "/v1/wallet/deposits/preview", input),
  startDeposit: (input: StartDeposit) => request<Deposit>("POST", "/v1/wallet/deposits", input),
  deposit: (id: string) => request<Deposit>("GET", `/v1/wallet/deposits/${encodeURIComponent(id)}`),
  banks: () => request<Bank[]>("GET", "/v1/wallet/banks"),
  resolveBankAccount: (input: BankAccount) =>
    request<ResolvedAccount>("POST", "/v1/wallet/bank-accounts/resolve", input),
  withdraw: (input: WithdrawInput) => request<Withdrawal>("POST", "/v1/wallet/withdraw", input),
  withdrawCrypto: (input: CryptoWithdrawInput) =>
    request<Withdrawal>("POST", "/v1/wallet/withdraw/crypto", input),
  suggestions: () => request<Suggestion[]>("GET", "/v1/suggestions"),
  approvals: () => request<PaymentRequest[]>("GET", "/v1/approvals"),
  demo: () => request<DemoSnapshot>("GET", "/v1/demo"),
  payees: () => request<Payee[]>("GET", "/v1/payees"),
  approve: (id: string) =>
    request<ApprovedPayment>("POST", `/v1/approvals/${encodeURIComponent(id)}/approve`, {}),
  deny: (id: string) =>
    request<PaymentRequest>("POST", `/v1/approvals/${encodeURIComponent(id)}/deny`, {}),
  pause: () => request<Controls>("POST", "/v1/controls/pause", {}),
  resume: () => request<Controls>("POST", "/v1/controls/resume", {}),
  /** Deletes the provider's session row, so the token this tab held cannot be replayed. */
  logout: () => request<{ logged_out: true }>("POST", "/v1/auth/logout", {}),
  /** A fresh single-use code for linking a chat. Every call mints a new one. */
  linkCode: () => request<LinkCode>("POST", "/v1/link/code", {}),
  linkedChats: () => request<LinkedChat[]>("GET", "/v1/link/identities"),
  unlinkChat: (chat: LinkedChat) =>
    request<{ unlinked: true; channel: string; channel_user_id: string }>(
      "DELETE",
      `/v1/link/identities/${encodeURIComponent(chat.channel)}/${encodeURIComponent(chat.channel_user_id)}`,
    ),
  voice: (transcript_hint: string, opts?: { speak?: boolean }) =>
    request<VoiceReply>("POST", "/v1/voice", {
      transcript_hint,
      ...(opts?.speak === undefined ? {} : { speak: opts.speak }),
    }),
  /**
   * Uploads the clip for server-side transcription (Whisper), for browsers without the Web Speech
   * API. The reply's `stt` field says whether the server heard it.
   */
  voiceAudio: async (audio: Blob, opts?: { speak?: boolean }) =>
    request<VoiceReply>("POST", "/v1/voice", {
      audio: await blobToBase64(audio),
      audio_type: audio.type || "audio/webm",
      ...(opts?.speak === undefined ? {} : { speak: opts.speak }),
    }),
  speak: (text: string) => request<SpeakReply>("POST", "/v1/speak", { text }),
  /**
   * A URL that streams the voice from its first bytes; fall back to `speak` if it errors. An
   * `<audio>` element cannot send `Authorization`, so the URL carries a two-minute ticket for this
   * text instead of the session token.
   */
  speakStreamUrl: async (text: string) => {
    const { url } = await request<SpeakTicket>("POST", "/v1/speak/ticket", { text });
    return `${baseUrl}${url}`;
  },
  /** An API-relative path from a reply (`speak_url`), as something `<audio>` can play. */
  streamUrl: (path: string) => `${baseUrl}${path}`,
  /** Stub only: restores the seeded demo state. Never call it while someone is demoing. */
  resetDemo: () => request<unknown>("POST", "/v1/_stub/reset", {}),
};
