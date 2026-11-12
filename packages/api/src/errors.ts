export type ApiErrorCode =
  | "unknown_bill"
  | "bad_amount"
  | "over_per_payment_cap"
  | "over_cap"
  | "insufficient_balance"
  | "bad_kind"
  | "bad_reference"
  | "bad_bill"
  | "unsupported_product"
  | "plan_required"
  | "unknown_plan"
  | "duplicate_bill"
  | "bill_in_flight"
  | "bad_limits"
  | "vendor_failed"
  | "paused"
  | "request_closed"
  | "unknown_request"
  | "no_route"
  | "not_available"
  | "provider_failed"
  | "bad_asset"
  | "bad_account"
  | "bad_address"
  | "over_limit"
  | "below_minimum"
  | "daily_limit"
  | "float_low"
  | "authorisation_failed"
  | "unknown_identity"
  | "network";

/** Every non-2xx response. Branch on `code`; `message` is copy and may change. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: ApiErrorCode | (string & {}),
    message: string,
    readonly detail: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function isApiError(error: unknown, code?: ApiErrorCode): error is ApiError {
  return error instanceof ApiError && (code === undefined || error.code === code);
}

/** Our own copy for each code. Only `vendor_failed` shows the server's message, which is written for people. */
export function errorCopy(error: unknown): string {
  if (!(error instanceof ApiError)) return "Something went wrong. Please try again.";
  switch (error.code) {
    case "over_per_payment_cap":
      return "That’s over your limit for a single payment.";
    case "over_cap":
      return "That would go over your monthly limit.";
    case "insufficient_balance":
      return "There isn’t enough in your wallet for that.";
    case "unknown_bill":
      return "That bill no longer exists.";
    case "paused":
      return "Stark is paused. Resume it to pay.";
    case "request_closed":
      return "That request was already decided or has expired.";
    case "bad_amount":
      return "Enter an amount in whole naira.";
    case "vendor_failed":
      return `${error.message} Nothing was charged.`;
    case "duplicate_bill":
      return "You’ve already saved that bill.";
    case "bill_in_flight":
      return "A payment for this bill is still going through. Try again in a moment.";
    case "bad_limits":
      return "Limits must be above zero, and a single payment can’t be more than the monthly limit.";
    case "bad_reference":
      return "That number doesn’t look right. Check it and try again.";
    case "unsupported_product":
      return "We can’t pay that provider yet.";
    case "plan_required":
    case "unknown_plan":
      return "Pick a plan first.";
    case "not_available":
    case "provider_failed":
    case "bad_account":
    case "bad_address":
    case "over_limit":
    case "below_minimum":
    case "daily_limit":
    case "float_low":
    case "authorisation_failed":
      return error.message;
    case "bad_asset":
      return "Pick what you’re paying with.";
    case "unknown_identity":
      return "That chat is no longer linked.";
    case "network":
      return "Can’t reach Stark right now. Check your connection.";
    default:
      return "Something went wrong. Please try again.";
  }
}
