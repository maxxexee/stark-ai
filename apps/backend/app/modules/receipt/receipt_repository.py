"""The receipt store — Postgres over Neon's HTTP endpoint.

Two things live here that matter more than the storage itself:

1. **`request_id` is the idempotency key.** It is the bill's `reference` at
   Flutterwave, which refuses a reused one. A receipt therefore stores its
   `request_id` from the moment it is created, and a retry of the same intent finds
   that row and reuses the id. `find_pending()` is how the payment path does it.
2. **The wallet is persisted next to the receipts.** Otherwise a restart would keep
   the history but forget the balance, and the two would disagree — which is exactly
   the kind of bug that makes a demo lie.

Everything is scoped to an account (`user_id`), because accounts are real now: two
people can sign up and neither sees the other's balance, history or bills.

**There are no transactions to open here.** Neon's HTTP endpoint runs one statement
per request and refuses multi-statement strings, so the money paths are written as
single statements that do both halves at once — `WITH w AS (UPDATE wallets ...)
INSERT INTO receipts ... SELECT ... FROM w`. If the balance cannot cover a charge the
`UPDATE` matches no row, the `INSERT` has nothing to select from, and nothing is
written. Never split one of those into two queries.

Money is integer naira. Units are a float because the tariff is fractional, and
units are not money.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.database import neon

RECEIPT_COLUMNS = (
    "id", "user_id", "request_id", "bill_id", "bill_label", "meter", "amount_ngn",
    "units", "token", "tx_hash", "status", "entry_type", "source",
    "vendor", "vendor_code", "vendor_ref", "vendor_message", "created_at", "fee_ngn",
)

UPDATABLE = frozenset({
    "units", "token", "tx_hash", "status", "vendor", "vendor_code", "vendor_ref",
    "vendor_message",
})


def _insert_sql(*, from_wallet: bool = False) -> tuple[str, int, int]:
    """The `INSERT INTO receipts` head, plus where `user_id` and the amount sit.

    `from_wallet=True` is the all-or-nothing form: the row is selected out of the
    `w` CTE that just moved the balance, so a short wallet writes nothing at all.
    """
    columns = ", ".join(RECEIPT_COLUMNS)
    placeholders = ", ".join(f"${i}" for i in range(1, len(RECEIPT_COLUMNS) + 1))
    tail = f"SELECT {placeholders} FROM w" if from_wallet else f"VALUES ({placeholders})"
    return (
        f"INSERT INTO receipts ({columns}) {tail}",
        RECEIPT_COLUMNS.index("user_id") + 1,
        len(RECEIPT_COLUMNS) + 1,
    )


def _typed(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """A receipt row with `amount_ngn` and `fee_ngn` as ints.

    Neon's HTTP endpoint returns `BIGINT` as a JSON **string** (JSON numbers can't
    hold 64 bits safely), so without this the amount comes back as `"5000"` and
    ends up in `/v1/bills` as a string the UI has to guess about. Money is integer
    naira everywhere in this codebase, so it is an int the moment it leaves a query.
    """
    if row is None:
        return row
    for column in ("amount_ngn", "fee_ngn"):
        if row.get(column) is not None:
            row[column] = int(row[column])
    return row


def _values(receipt: dict[str, Any], user_id: str) -> list[Any]:
    row = {**receipt, "user_id": user_id, "fee_ngn": receipt.get("fee_ngn") or 0}
    return [row.get(column) for column in RECEIPT_COLUMNS]


class ReceiptRepository:
    def __init__(self, db: neon.Database | None = None) -> None:
        self.db = db or neon.open_database()

    # --- receipts ------------------------------------------------------------

    def create(self, user_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
        head, _, _ = _insert_sql()
        row = self.db.one(f"{head} RETURNING *", _values(receipt, user_id))
        return _typed(row) or {}

    def update(self, user_id: str, receipt_id: str, **fields: Any) -> dict[str, Any] | None:
        unknown = set(fields) - UPDATABLE
        if unknown:
            raise ValueError(f"cannot update {sorted(unknown)}")
        if not fields:
            return self.get(user_id, receipt_id)
        assignments = ", ".join(
            f"{name} = ${index + 3}" for index, name in enumerate(fields)
        )
        self.db.query(
            f"UPDATE receipts SET {assignments} WHERE id = $1 AND user_id = $2",
            [receipt_id, user_id, *fields.values()],
        )
        return self.get(user_id, receipt_id)

    def get(self, user_id: str, receipt_id: str) -> dict[str, Any] | None:
        return _typed(self.db.one(
            "SELECT * FROM receipts WHERE id = $1 AND user_id = $2", [receipt_id, user_id]
        ))

    def by_request_id(self, user_id: str, request_id: str) -> dict[str, Any] | None:
        return _typed(self.db.one(
            "SELECT * FROM receipts WHERE request_id = $1 AND user_id = $2",
            [request_id, user_id],
        ))

    def has_pending(self, user_id: str, bill_id: str) -> bool:
        row = self.db.one(
            "SELECT 1 AS found FROM receipts"
            " WHERE user_id = $1 AND bill_id = $2 AND status = 'pending' LIMIT 1",
            [user_id, bill_id],
        )
        return row is not None

    def find_pending(
        self, user_id: str, bill_id: str, amount_ngn: int
    ) -> dict[str, Any] | None:
        """The newest unfinished purchase for this exact intent.

        A retry must settle this one, by its `vendor_ref`, rather than buy again.
        """
        return _typed(self.db.one(
            "SELECT * FROM receipts WHERE user_id = $1 AND bill_id = $2"
            " AND amount_ngn = $3 AND status = 'pending'"
            " ORDER BY created_at DESC, seq DESC LIMIT 1",
            [user_id, bill_id, amount_ngn],
        ))

    def recent(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return [
            _typed(row) or {}
            for row in self.db.query(
                "SELECT * FROM receipts WHERE user_id = $1"
                " ORDER BY created_at DESC, seq DESC LIMIT $2",
                [user_id, int(limit)],
            )
        ]

    def paid_by_bill(self, user_id: str, month_start: str) -> dict[str, dict[str, int]]:
        """Delivered bill payments per bill: all-time total, this month, and count."""
        rows = self.db.query(
            "SELECT bill_id, COALESCE(SUM(amount_ngn), 0) AS total,"
            " COALESCE(SUM(amount_ngn) FILTER (WHERE created_at >= $2), 0) AS month,"
            " COUNT(*) AS payments"
            " FROM receipts WHERE user_id = $1 AND status = 'delivered'"
            # Bill payments predate `entry_type`, so an unset one is a bill.
            " AND COALESCE(entry_type, 'bill') IN ('bill', 'autotopup') GROUP BY bill_id",
            [user_id, month_start],
        )
        return {row["bill_id"]: {"total": int(row["total"]), "month": int(row["month"]),
                                 "payments": int(row["payments"])} for row in rows}

    def count(self, user_id: str) -> int:
        return int(self.db.value(
            "SELECT COUNT(*) FROM receipts WHERE user_id = $1", [user_id]
        ) or 0)

    # --- wallet --------------------------------------------------------------

    def wallet(self, user_id: str) -> dict[str, int] | None:
        row = self.db.one(
            "SELECT balance_ngn, spent_ngn FROM wallets WHERE user_id = $1", [user_id]
        )
        if row is None:
            return None
        return {"balance_ngn": int(row["balance_ngn"]), "spent_ngn": int(row["spent_ngn"])}

    def set_wallet(self, user_id: str, balance_ngn: int, spent_ngn: int) -> None:
        self.db.query(
            "INSERT INTO wallets (user_id, balance_ngn, spent_ngn) VALUES ($1, $2, $3)"
            " ON CONFLICT (user_id) DO UPDATE SET balance_ngn = EXCLUDED.balance_ngn,"
            " spent_ngn = EXCLUDED.spent_ngn",
            [user_id, int(balance_ngn), int(spent_ngn)],
        )

    def record_deposit(
        self, user_id: str, receipt: dict[str, Any], amount_ngn: int
    ) -> tuple[dict[str, Any], dict[str, int]]:
        """Insert the activity entry and credit the wallet in one statement."""
        head, user_index, amount_index = _insert_sql()
        values = _values(receipt, user_id)
        row = self.db.one(
            f"WITH r AS ({head} RETURNING *)"
            f", w AS (UPDATE wallets SET balance_ngn = balance_ngn + ${amount_index}"
            f" WHERE user_id = ${user_index} RETURNING balance_ngn, spent_ngn)"
            " SELECT (SELECT row_to_json(r) FROM r) AS receipt,"
            " (SELECT row_to_json(w) FROM w) AS wallet",
            [*values, int(amount_ngn)],
        )
        # The wallet CTE matched nothing, so nothing was written: no account row.
        if row is None or row.get("wallet") is None:
            raise ValueError("account_missing")
        return _typed(row["receipt"]) or {}, {
            "balance_ngn": int(row["wallet"]["balance_ngn"]),
            "spent_ngn": int(row["wallet"]["spent_ngn"]),
        }

    def record_debit(
        self, user_id: str, receipt: dict[str, Any], amount_ngn: int
    ) -> tuple[dict[str, Any], dict[str, int]]:
        """Insert the activity entry and debit the wallet, or raise if short.

        This is how money is held before it goes anywhere: a withdrawal before it is
        sent, a bill purchase before the vendor is called (closed by `finish`).
        """
        head, user_index, amount_index = _insert_sql(from_wallet=True)
        values = _values(receipt, user_id)
        amount = int(amount_ngn)
        row = self.db.one(
            f"WITH w AS (UPDATE wallets SET balance_ngn = balance_ngn - ${amount_index}"
            f" WHERE user_id = ${user_index} AND balance_ngn >= ${amount_index}"
            " RETURNING balance_ngn, spent_ngn)"
            f", r AS ({head} RETURNING *)"
            " SELECT (SELECT row_to_json(r) FROM r) AS receipt,"
            " (SELECT row_to_json(w) FROM w) AS wallet",
            [*values, amount],
        )
        # A short wallet matches no row in `w`, so `r` inserted nothing and both
        # sub-selects come back NULL. That is the refusal, not an empty result.
        if row is None or row.get("wallet") is None:
            raise ValueError("insufficient_balance")
        return _typed(row["receipt"]) or {}, {
            "balance_ngn": int(row["wallet"]["balance_ngn"]),
            "spent_ngn": int(row["wallet"]["spent_ngn"]),
        }

    def added_this_month(self, user_id: str) -> int:
        """Deposits that landed since the first of the current UTC month."""
        month_start = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        return int(self.db.value(
            "SELECT COALESCE(SUM(amount_ngn), 0) FROM receipts"
            " WHERE user_id = $1 AND entry_type = 'deposit' AND status = 'received'"
            " AND created_at >= $2",
            [user_id, month_start],
        ) or 0)

    def units_bought(self, user_id: str) -> tuple[float, str | None]:
        """Electricity units ever delivered, and when the first of them landed.

        Only electricity top-ups carry `units`; airtime and TV leave it null.
        """
        row = self.db.one(
            "SELECT COALESCE(SUM(units), 0) AS units, MIN(created_at) AS first_at"
            " FROM receipts"
            " WHERE user_id = $1 AND status = 'delivered' AND units IS NOT NULL",
            [user_id],
        )
        return float(row["units"]), row["first_at"]

    def pending_purchases(self, created_before: str, limit: int = 50) -> list[dict[str, Any]]:
        """Bill purchases still in flight, across every account, oldest first."""
        return [
            _typed(row) or {}
            for row in self.db.query(
                "SELECT * FROM receipts WHERE status = 'pending' AND created_at <= $1"
                " AND COALESCE(entry_type, 'bill') IN ('bill', 'autotopup')"
                " ORDER BY created_at, seq LIMIT $2",
                [created_before, int(limit)],
            )
        ]

    def finish(self, user_id: str, receipt_id: str, status: str,
               **fields: Any) -> dict[str, Any] | None:
        """Close a pending purchase and settle the money it held, in one statement.

        The amount left the balance when the purchase was recorded (`record_debit`).
        `delivered` turns it into spend; `failed` puts it back in the balance. Only a
        receipt that is still `pending` moves, so when a retry and the background
        check settle the same purchase at once, exactly one of them does and the
        other gets None.
        """
        wallet = {
            "delivered": "spent_ngn = spent_ngn + r.amount_ngn + r.fee_ngn",
            "failed": "balance_ngn = balance_ngn + r.amount_ngn + r.fee_ngn",
        }[status]
        unknown = set(fields) - UPDATABLE
        if unknown:
            raise ValueError(f"cannot update {sorted(unknown)}")
        assignments = "".join(
            f", {name} = ${index + 4}" for index, name in enumerate(fields)
        )
        return _typed(self.db.one(
            f"WITH r AS (UPDATE receipts SET status = $3{assignments}"
            " WHERE id = $1 AND user_id = $2 AND status = 'pending' RETURNING *)"
            f", w AS (UPDATE wallets SET {wallet} FROM r WHERE wallets.user_id = r.user_id)"
            " SELECT * FROM r",
            [receipt_id, user_id, status, *fields.values()],
        ))

    def drop_hold(self, user_id: str, receipt_id: str) -> None:
        """Undo a purchase that was refused before anything was bought: the pending
        entry goes and its amount returns to the balance, in one statement."""
        self.db.query(
            "WITH r AS (DELETE FROM receipts"
            " WHERE id = $1 AND user_id = $2 AND status = 'pending'"
            " RETURNING user_id, amount_ngn, fee_ngn)"
            " UPDATE wallets SET balance_ngn = balance_ngn + r.amount_ngn + r.fee_ngn"
            " FROM r WHERE wallets.user_id = r.user_id",
            [receipt_id, user_id],
        )

    # --- test / demo seam ----------------------------------------------------

    def replace_all(self, user_id: str, receipts: Iterable[dict[str, Any]], *,
                    balance_ngn: int, spent_ngn: int) -> None:
        """Used by the stub-only reset route. Not part of the product.

        Not atomic: the HTTP endpoint cannot wrap a delete and N inserts in a
        transaction. It is a demo reset, so a half-applied reset is a rerun, not a
        lost payment.
        """
        self.db.query("DELETE FROM receipts WHERE user_id = $1", [user_id])
        for receipt in receipts:
            self.create(user_id, receipt)
        self.set_wallet(user_id, balance_ngn, spent_ngn)

    def close(self) -> None:
        self.db.close()


def api_shape(receipt: dict[str, Any]) -> dict[str, Any]:
    """The frozen `Receipt` shape, plus the additive fields the UI may ignore."""
    return {
        "id": receipt["id"],
        "bill_id": receipt["bill_id"],
        "bill_label": receipt["bill_label"],
        "amount_ngn": receipt["amount_ngn"],
        "units": receipt["units"],
        "token": receipt["token"],
        "tx_hash": receipt["tx_hash"],
        "created_at": receipt["created_at"],
        # Additive (2026-10-22): a pending purchase is not a completed one.
        "status": receipt["status"],
        "request_id": receipt["request_id"],
        # Additive (2026-10-22): `type` is `bill`, `autotopup` or `deposit`;
        # `source` is where the user asked for it (Telegram, wall phone, bank).
        # Live payments predate this column, so they default to `bill`.
        "type": receipt.get("entry_type") or "bill",
        "source": receipt.get("source"),
        # Additive (2026-11-03): why a `declined` entry was stopped, in plain words.
        "reason": receipt.get("vendor_message") if receipt["status"] == "declined" else None,
        # Additive (2026-11-12): Stark's service fee, charged on top of `amount_ngn`.
        "fee_ngn": receipt.get("fee_ngn") or 0,
    }
