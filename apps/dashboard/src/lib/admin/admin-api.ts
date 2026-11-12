import { ApiError } from "@stark/api/errors";

export interface TreasuryReport {
  owed_to_users_ngn: number;
  held: {
    /** null when Flutterwave could not be read: unknown, not zero. */
    flutterwave_ngn: number | null;
    pending_purchases_ngn: number;
    treasury_usdc_as_ngn: number | null;
  };
  /** A decimal string, so no float rounding on the way. */
  treasury_usdc: string | null;
  coverage_ngn: number;
  unsettled_vault_ops: number;
}

export interface StatusCount {
  method: string;
  status: string;
  count: number;
  amount_ngn: number;
}

export interface InFlightWithdrawal {
  id: string;
  user_id: string;
  method: string;
  amount_ngn: number;
  status: string;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface OpenDeposit {
  id: string;
  user_id: string;
  method: string;
  amount_ngn: number;
  status: string;
  created_at: string;
  expires_at: string | null;
}

export interface ChainSetup {
  network: "testnet" | "mainnet";
  funder: string;
  usdc: string;
}

export interface VaultRow {
  user_id: string;
  account_id: string;
  status: string;
  created_at: string;
  last_error: string | null;
}

/** A chain op that has not gone through: what holds a user's payments up, and why. */
export interface StuckChainOp {
  id: string;
  user_id: string;
  method: string;
  status: "pending" | "failed";
  attempts: number;
  last_error: string | null;
  created_at: string;
}

export interface AdminOverview {
  treasury: TreasuryReport;
  deposits: StatusCount[];
  withdrawals: StatusCount[];
  withdrawals_in_flight: InFlightWithdrawal[];
  deposits_open: OpenDeposit[];
  /** null when no chain is configured and payments book off-chain. */
  chain: ChainSetup | null;
  vaults: VaultRow[];
  /** Absent from an API deployed before it was added; the dashboard and API deploy apart. */
  chain_ops_stuck?: StuckChainOp[];
  /** The server's outbound IP, for Flutterwave's whitelist; null when it couldn't be read. */
  egress_ip: string | null;
  /** Absent from an API deployed before fees existed; the dashboard and API deploy apart. */
  fees_ngn?: Fees;
}

/** Stark's service fee on each kind of bill, in naira. */
export interface Fees {
  electricity: number;
  tv: number;
  airtime: number;
  data: number;
}

const KEY_STORAGE = "stark.admin-key";

/**
 * Admin routes take `X-Stark-Admin-Key` instead of a session; the key lives in sessionStorage, so
 * it is gone when the tab closes.
 */
export class AdminApi {
  static savedKey(): string | null {
    return sessionStorage.getItem(KEY_STORAGE);
  }

  static saveKey(key: string) {
    sessionStorage.setItem(KEY_STORAGE, key);
  }

  static forgetKey() {
    sessionStorage.removeItem(KEY_STORAGE);
  }

  static overview(key: string): Promise<AdminOverview> {
    return AdminApi.request(key, "/v1/admin/overview");
  }

  static async updateFees(key: string, fees: Partial<Fees>): Promise<Fees> {
    const data = await AdminApi.request<{ fees_ngn: Fees }>(key, "/v1/admin/fees", {
      method: "PATCH",
      body: JSON.stringify(fees),
    });
    return data.fees_ngn;
  }

  private static async request<T>(key: string, path: string, init: RequestInit = {}): Promise<T> {
    const base = (import.meta.env.VITE_STARK_API_URL ?? "").replace(/\/$/, "");
    let res: Response;
    try {
      res = await fetch(`${base}${path}`, {
        ...init,
        headers: { "X-Stark-Admin-Key": key, "Content-Type": "application/json" },
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
}
