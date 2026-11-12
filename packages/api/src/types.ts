export type BillKind = "electricity" | "airtime" | "data" | "tv" | "internet" | "water";

export type Bill = {
  id: string;
  kind: BillKind;
  provider: string;
  label: string;
  reference: string;
  last_amount_ngn: number | null;
  last_units: number | null;
  last_paid_at: string | null;
  plan?: string;
  plan_price_ngn?: number;
  renews_on?: string;
  fee_ngn?: number;
};

export type DueBill = {
  id: string;
  kind: BillKind;
  provider: string;
  label: string;
  renews_on: string;
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
  paused: boolean;
  units_left: number | null;
  days_left: number | null;
  bills: Bill[];
  due_soon: DueBill[];
  as_of: string;
};

export type ReceiptStatus = "delivered" | "pending" | "failed" | "declined" | "received" | "sent";
export type ReceiptType = "bill" | "autotopup" | "deposit" | "withdrawal";

export type Receipt = {
  id: string;
  bill_id: string;
  bill_label: string;
  amount_ngn: number;
  units: number | null;
  token: string | null;
  tx_hash?: string | null;
  created_at: string;
  status: ReceiptStatus;
  request_id?: string;
  type: ReceiptType;
  source: string | null;
  reason: string | null;
  fee_ngn?: number;
};

export type Plan = {
  kind: "data" | "tv";
  provider: string;
  service_name: string;
  plan: string;
  label: string;
  price_ngn: number;
};

export type Limits = {
  monthly_cap_ngn: number;
  per_payment_cap_ngn: number;
  spent_ngn: number;
  remaining_cap_ngn: number;
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
  text: string;
  severity: "info" | "warn" | "alert";
  reason: string;
};

export type VoiceReply = {
  transcript: string;
  ignored: boolean;
  reply: string | null;
  token: string | null;
  receipt_id: string | null;
  deposit?: Deposit | null;
  audio?: string | null;
  stt?: "ok" | "no_key" | "failed";
};

export type SpeakReply = {
  audio: string | null;
};

export type NewBill = {
  kind: BillKind;
  provider: string;
  reference: string;
  label?: string;
  plan?: string;
  renews_on?: string;
};

export type BillPatch = {
  label?: string;
  plan?: string;
  renews_on?: string;
};
export type LinkCode = {
  code: string;
  channel: string;
  expires_in: number;
  bot_username: string | null;
  deep_link: string | null;
  user_id?: string;
};

export type LimitsPatch = {
  monthly_cap_ngn?: number;
  per_payment_cap_ngn?: number;
  approval_window_minutes?: ApprovalWindow;
};
export type PaymentInput = { bill_id: string; amount_ngn: number };
export type TopUpInput = { amount_ngn: number; request_id?: string };

export type Controls = {
  paused: boolean;
  paused_at: string | null;
};

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
  receipt_id: string | null;
};

export type ApprovedPayment = { request: PaymentRequest; receipt: Receipt };

export type DemoSnapshot = {
  state: State;
  activity: Receipt[];
  approvals: PaymentRequest[];
  limits: Pick<Limits, "monthly_cap_ngn" | "per_payment_cap_ngn">;
};

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

export type FundingMethods = {
  bank: boolean;
  crypto: boolean;
  test_money: boolean;
  withdraw: { bank: boolean; crypto: boolean };
};

export type UsdcRates = { deposit: string; withdraw: string };

export type DepositPreviewInput =
  | { asset_id: string; amount_ngn: number }
  | { asset_id: string; amount_in: string };

export type DepositPreview = {
  asset_id: string;
  amount_ngn: number;
  amount_in: string;
  rate: string;
};

export type CryptoAsset = { asset_id: string; symbol: string; chain: string };

export type DepositStatus = "open" | "confirming" | "credited" | "expired" | "failed" | "refunded";

type DepositCommon = {
  id: string;
  amount_ngn: number;
  credited_ngn: number | null;
  status: DepositStatus;
  note: string | null;
  expires_at: string | null;
  created_at: string;
  credited_at: string | null;
};

export type Deposit = DepositCommon &
  (
    | { method: "bank"; pay: { checkout_url: string } }
    | {
        method: "crypto";
        pay: {
          asset: string;
          chain: string;
          amount: string;
          address: string;
          memo: string | null;
        };
      }
  );

export type StartDeposit =
  | { method: "bank"; amount_ngn: number }
  | { method: "crypto"; amount_ngn: number; asset_id: string };

export type Bank = { name: string; code: string };

export type BankAccount = { bank_code: string; account_number: string };

export type ResolvedAccount = BankAccount & { account_name: string };

export type WithdrawInput = BankAccount & { amount_ngn: number };

export type CryptoWithdrawInput = {
  amount_ngn: number;
  asset_id: string;
  address: string;
};

type WithdrawalCommon = {
  id: string;
  amount_ngn: number;
  note: string | null;
  created_at: string;
  updated_at: string;
};

export type Withdrawal = WithdrawalCommon &
  (
    | {
        method: "bank";
        status: "sending" | "processing" | "paid" | "returned";
        crypto: null;
      }
    | {
        method: "crypto";
        status: "sending" | "processing" | "paid" | "returned";
        crypto: {
          asset: string;
          chain: string;
          address: string;
          amount: string;
          tx_hash: string | null;
        };
      }
  );
