import { ApiError } from "@stark/api/errors";

export interface TreasuryReport {
  owed_to_users_ngn: number;
  held: {
    flutterwave_ngn: number | null;
    pending_purchases_ngn: number;
    treasury_usdc_as_ngn: number | null;
    /** null when the vaults could not be read, or there are none on chain. */
    vaults_usdc_as_ngn: number | null;
  };
  treasury_usdc: string | null;
  /** Every user vault's USDC together. null when vaults are off or never broadcast. */
  vaults: {
    network: "testnet" | "mainnet";
    /** null when the read failed: unknown, not zero. */
    count: number | null;
    usdc: string | null;
    /** Testnet vaults hold test tokens, so only mainnet ones count toward coverage. */
    counted: boolean;
  } | null;
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

export interface OperatorAlert {
  kind: "flutterwave" | "treasury" | "coverage";
  message: string;
  raised_at: string;
  cleared_at: string | null;
  cleared_message: string | null;
  updated_at: string;
}

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
  chain: ChainSetup | null;
  vaults: VaultRow[];
  chain_ops_stuck?: StuckChainOp[];
  alerts?: OperatorAlert[];
  egress_ip: string | null;
  fees_ngn?: Fees;
  limits?: OperatorLimit[];
}

/** One operator limit; the API owns the set, so a key the page does not know still shows. */
export interface OperatorLimit {
  key: string;
  label: string;
  unit: string;
  value: number;
  default: number;
  minimum: number;
  maximum: number;
  overridden: boolean;
}

export interface Fees {
  electricity: number;
  tv: number;
  airtime: number;
  data: number;
}

const KEY_STORAGE = "stark.admin-key";

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

  /** `null` puts a limit back on its default. */
  static async updateLimits(
    key: string,
    changes: Record<string, number | null>,
  ): Promise<OperatorLimit[]> {
    const data = await AdminApi.request<{ limits: OperatorLimit[] }>(key, "/v1/admin/limits", {
      method: "PATCH",
      body: JSON.stringify(changes),
    });
    return data.limits;
  }

  private static async request<T>(key: string, path: string, init: RequestInit = {}): Promise<T> {
    const base = (import.meta.env.VITE_STARK_API_URL ?? "").replace(/\/$/, "");
    let res: Response;
    try {
      res = await fetch(`${base}${path}`, {
        ...init,
        headers: {
          "X-Stark-Admin-Key": key,
          "Content-Type": "application/json",
        },
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
