// Shapes from docs/API.md (contract v1, frozen). Additive changes only: add fields here,
// never rename or retype them. Money is integer naira; times are ISO 8601 UTC strings.

export type BillKind = "electricity" | "airtime" | "data" | "tv" | "internet" | "water";

export type Bill = {
  id: string;
  kind: BillKind;
  provider: string;
  label: string;
  /** Meter, phone or smartcard number. Never a wallet address. */
  reference: string;
  last_amount_ngn: number | null;
  last_units: number | null;
  last_paid_at: string | null;
  /** Data and TV only: the vendor plan code and its fixed price. */
  plan?: string;
  plan_price_ngn?: number;
  /** Additive: when this bill is supposed to be paid, YYYY-MM-DD. Absent for
   *  meters and lines that do not renew on a schedule. */
  renews_on?: string;
};

/** A bill with a renewal inside the reminder window — the shape of `State.due_soon`. */
export type DueBill = {
  id: string;
  kind: BillKind;
  provider: string;
  label: string;
  /** YYYY-MM-DD. */
  renews_on: string;
  /** 0 is today, negative is overdue. */
  days_until: number;
  price_ngn: number | null;
};

export type State = {
  user_id: string;
  first_name: string;
  currency: "NGN";
  balance_ngn: number;
  cap_ngn: number;
  spent_ngn: number;
  remaining_cap_ngn: number;
  /** True while the owner has paused Stark: every payment is refused. */
  paused: boolean;
  /** null when the user has no electricity bill: hide the block, don't show 0. */
  units_left: number | null;
  /** An estimate from purchase history, not a precise number. */
  days_left: number | null;
  bills: Bill[];
  /** Additive: bills due inside the reminder window, soonest first. */
  due_soon: DueBill[];
  as_of: string;
};

export type ReceiptStatus = "delivered" | "pending" | "failed" | "declined" | "received" | "sent";
export type ReceiptType = "bill" | "autotopup" | "deposit" | "withdrawal";

export type Receipt = {
  id: string;
  /** `"wallet"` for deposits and withdrawals. */
  bill_id: string;
  bill_label: string;
  amount_ngn: number;
  units: number | null;
  /** Electricity only. */
  token: string | null;
  /** The vault's `pay` transaction on NEAR testnet; the receipt links to it. */
  tx_hash?: string | null;
  created_at: string;
  status: ReceiptStatus;
  request_id?: string;
  type: ReceiptType;
  source: string | null;
  /** Why a `declined` entry was stopped, in plain words; null otherwise. */
  reason: string | null;
};

export type Plan = {
  kind: "data" | "tv";
  provider: string;
  service_name: string;
  plan: string;
  /** The vendor's own label. Render as-is. */
  label: string;
  price_ngn: number;
};

export type Limits = {
  monthly_cap_ngn: number;
  per_payment_cap_ngn: number;
  spent_ngn: number;
  remaining_cap_ngn: number;
  /** How long a payment over a limit waits for approval. */
  approval_window_minutes: ApprovalWindow;
};

export type ApprovalWindow = 15 | 30 | 60 | 360 | 1440;

export type Wallet = {
  currency: "NGN";
  balance_ngn: number;
  spent_ngn: number;
  monthly_cap_ngn: number;
  remaining_cap_ngn: number;
  added_this_month_ngn: number;
};

export type WalletMovement = {
  wallet: Wallet;
  entry: Receipt;
};

export type Suggestion = {
  id: string;
  /** Finished copy. Render, don't reassemble. */
  text: string;
  severity: "info" | "warn" | "alert";
  /** Debugging only. */
  reason: string;
};

export type VoiceReply = {
  transcript: string;
  /** true when the wake word was missing: stay completely silent. */
  ignored: boolean;
  reply: string | null;
  token: string | null;
  receipt_id: string | null;
  /** Additive: the reply spoken by the local voice, as a WAV data URL.
   *  null when voice is off (no sidecar configured, or it did not answer). */
  audio?: string | null;
  /** Additive: set when the transcript came from server-side speech-to-text
   *  (an uploaded clip). `"ok"`, or why the clip came back unheard — in which
   *  case `transcript` is empty and `reply` says so. */
  stt?: "ok" | "no_key" | "failed";
};

/** Reply of `POST /v1/speak` — a fetched voice, WAV data URL or null. */
export type SpeakReply = {
  audio: string | null;
};

export type NewBill = {
  kind: BillKind;
  provider: string;
  reference: string;
  label?: string;
  plan?: string;
  /** Additive: when the bill should be paid, YYYY-MM-DD. */
  renews_on?: string;
};

export type BillPatch = {
  label?: string;
  plan?: string;
  /** Additive: set a date (YYYY-MM-DD) or clear it with "". */
  renews_on?: string;
};
/**
 * A single-use code that binds a chat to this account. Returned once, by
 * `POST /v1/link/code`; the server keeps only a hash of it.
 */
export type LinkCode = {
  code: string;
  channel: string;
  /** Seconds until it expires. */
  expires_in: number;
  bot_username: string | null;
  /** `https://t.me/<bot>?start=<code>` — null when the bot has no token. */
  deep_link: string | null;
  user_id?: string;
};

export type LimitsPatch = {
  monthly_cap_ngn?: number;
  per_payment_cap_ngn?: number;
  approval_window_minutes?: ApprovalWindow;
};
export type PaymentInput = { bill_id: string; amount_ngn: number };
/** Test money: there is no payment provider yet, so nothing is collected. */
export type TopUpInput = { amount_ngn: number; request_id?: string };

export type Controls = {
  paused: boolean;
  /** When Stark was paused; null while it may pay. */
  paused_at: string | null;
};

/** A payment over a limit, waiting for the owner. Only `pending` can be decided. */
export type PaymentRequest = {
  id: string;
  bill_id: string;
  bill_label: string;
  amount_ngn: number;
  reason: "over_per_payment_cap" | "over_cap";
  status: "pending" | "approved" | "denied" | "expired";
  created_at: string;
  expires_at: string;
  decided_at: string | null;
  /** The payment an approval became. */
  receipt_id: string | null;
};

export type ApprovedPayment = { request: PaymentRequest; receipt: Receipt };

/** The public sample account. Made up, read-only, and served without a session. */
export type DemoSnapshot = {
  state: State;
  activity: Receipt[];
  approvals: PaymentRequest[];
  limits: Pick<Limits, "monthly_cap_ngn" | "per_payment_cap_ngn">;
};

/** A saved bill seen as somewhere Stark may pay. Only delivered payments count. */
export type Payee = {
  bill_id: string;
  label: string;
  kind: BillKind;
  provider: string;
  reference: string;
  paid_this_month_ngn: number;
  paid_total_ngn: number;
  payments: number;
  last_paid_at: string | null;
};

/** Which ways of adding (and taking out) money the server has switched on. */
export type FundingMethods = {
  bank: boolean;
  crypto: boolean;
  test_money: boolean;
  withdraw: { bank: boolean; crypto: boolean };
};

/** Naira per USDC right now, as decimal strings: what a deposit credits, what a
 * withdrawal costs. A quote locks its own rate when it is made. */
export type UsdcRates = { deposit: string; withdraw: string };

/** Price a crypto deposit from whichever side the user typed. `amount_in` is a decimal
 * string in the asset. */
export type DepositPreviewInput =
  | { asset_id: string; amount_ngn: number }
  | { asset_id: string; amount_in: string };

/** What a crypto deposit would take (`amount_in`, in the asset) and credit (`amount_ngn`). */
export type DepositPreview = {
  asset_id: string;
  amount_ngn: number;
  amount_in: string;
  rate: string;
};

/** Something a crypto deposit can be paid with (NEAR Intents routes it to naira). */
export type CryptoAsset = { asset_id: string; symbol: string; chain: string };

export type DepositStatus = "open" | "confirming" | "credited" | "expired" | "failed" | "refunded";

type DepositCommon = {
  id: string;
  amount_ngn: number;
  /** What actually landed; null until credited. */
  credited_ngn: number | null;
  status: DepositStatus;
  /** Why it failed or was refunded, when it was. */
  note: string | null;
  expires_at: string | null;
  created_at: string;
  credited_at: string | null;
};

/** `bank` pays on Flutterwave's hosted page; `crypto` is a one-off address for an exact amount. */
export type Deposit = DepositCommon &
  (
    | { method: "bank"; pay: { checkout_url: string } }
    | {
        method: "crypto";
        pay: { asset: string; chain: string; amount: string; address: string; memo: string | null };
      }
  );

export type StartDeposit =
  | { method: "bank"; amount_ngn: number }
  | { method: "crypto"; amount_ngn: number; asset_id: string };

export type Bank = { name: string; code: string };

export type BankAccount = { bank_code: string; account_number: string };

export type ResolvedAccount = BankAccount & { account_name: string };

export type WithdrawInput = BankAccount & { amount_ngn: number };

/** `asset_id` comes from `cryptoAssets`; `address` is the user's, on that asset's chain. */
export type CryptoWithdrawInput = { amount_ngn: number; asset_id: string; address: string };

type WithdrawalCommon = {
  id: string;
  amount_ngn: number;
  /** Why it was returned, when it was. */
  note: string | null;
  created_at: string;
  updated_at: string;
};

/**
 * `sending`: the transfer is going out (a bank transfer Flutterwave has not taken yet,
 * or the swap for a crypto withdrawal). `returned`: the money came back to the balance.
 */
export type Withdrawal = WithdrawalCommon &
  (
    | { method: "bank"; status: "sending" | "processing" | "paid" | "returned"; crypto: null }
    | {
        method: "crypto";
        status: "sending" | "processing" | "paid" | "returned";
        crypto: {
          asset: string;
          chain: string;
          address: string;
          /** What arrives: the quote until the swap settles, then the settled amount. */
          amount: string;
          tx_hash: string | null;
        };
      }
  );
