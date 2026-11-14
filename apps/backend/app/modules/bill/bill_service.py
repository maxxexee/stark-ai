"""Saved bills: add, edit, remove, and keep in step with delivered payments.

Every change is written through to `bills` and re-scopes the agent's meter
allowlist, so the agent can pay a new bill (and cannot pay a removed one) in the
very next turn.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from app.common.api_error import ApiError
from app.common.clock import Clock
from app.modules.account.account_repository import AccountRepository
from app.modules.account.account_service import AccountService
from app.modules.bill.bill_kind import PLAN_KINDS, BillKind
from app.modules.bill.dtos.create_bill_dto import CreateBillDto
from app.modules.bill.dtos.update_bill_dto import UpdateBillDto
from app.modules.receipt.receipt_repository import ReceiptRepository
from app.modules.reminder import reminders
from app.modules.settings.settings_service import SettingsService
from app.modules.vending import catalog

# A label and a provider are names, and both are read to the agent as part of its
# prompt: free text there is a place to hide instructions. Letters (any script),
# digits, spaces and the punctuation a real name uses; nothing else.
LABEL_MAX = 40
# The longest disco, written out, is "Port Harcourt Electricity Distribution Company".
PROVIDER_MAX = 48
_NAME = re.compile(r"(?:[^\W_]|[ .,'&()/-])+")


class BillService:
    def __init__(self, accounts: AccountService, repository: AccountRepository,
                 receipts: ReceiptRepository, settings: SettingsService) -> None:
        self.accounts = accounts
        self.repository = repository
        self.receipts = receipts
        self.settings = settings

    def public(self, account_id: str) -> list[dict[str, Any]]:
        """The bills with the service fee a payment to each would carry right now."""
        fees = self.settings.fees()
        return [{**bill, "fee_ngn": fees.get(bill["kind"], 0)}
                for bill in self.bills(account_id).values()]

    def bills(self, account_id: str) -> dict[str, dict[str, Any]]:
        return self.accounts.state(account_id).bills

    def payees(self, account_id: str) -> list[dict[str, Any]]:
        """Everyone Stark may pay — the saved bills — and what each has been paid.

        Only delivered payments count, the same rule as the monthly spend.
        """
        paid = self.receipts.paid_by_bill(account_id, Clock.month_start())
        none = {"total": 0, "month": 0, "payments": 0}
        return [{
            "bill_id": bill["id"],
            "label": bill["label"],
            "kind": bill["kind"],
            "provider": bill["provider"],
            "reference": bill["reference"],
            "paid_this_month_ngn": paid.get(bill["id"], none)["month"],
            "paid_total_ngn": paid.get(bill["id"], none)["total"],
            "payments": paid.get(bill["id"], none)["payments"],
            "last_paid_at": bill["last_paid_at"],
        } for bill in self.bills(account_id).values()]

    def public_bill(self, account_id: str, bill_id: str) -> dict[str, Any]:
        bill = self.get(account_id, bill_id)
        return {**bill, "fee_ngn": self.settings.fee_for(bill["kind"])}

    def get(self, account_id: str, bill_id: str) -> dict[str, Any]:
        bill = self.bills(account_id).get(bill_id)
        if bill is None:
            raise ApiError(404, "unknown_bill", f"No bill {bill_id}")
        return bill

    def add(self, account_id: str, dto: CreateBillDto) -> dict[str, Any]:
        """Save a bill, payable at once.

        A bill saved from a chat is the owner's own instruction, so there is no
        second step. The caps, the pause and the balance still gate every
        payment, whichever door it came through.
        """
        kind = dto.kind.strip().lower()
        if kind not in BillKind.values():
            raise ApiError(400, "bad_kind",
                           f"kind must be one of {', '.join(BillKind.values())}")
        provider = self._name(dto.provider, "provider", PROVIDER_MAX)
        reference = re.sub(r"\s+", "", dto.reference)
        if not 4 <= len(reference) <= 32:
            raise ApiError(400, "bad_reference", "reference must be 4–32 characters")
        label = self._name(dto.label, "label", LABEL_MAX) if dto.label.strip() else provider
        plan = dto.plan.strip() or None
        plan_price = None
        renews_on = self._renews_on(dto.renews_on) if dto.renews_on else None

        if kind in (BillKind.ELECTRICITY, BillKind.AIRTIME, BillKind.DATA, BillKind.TV):
            # Each disco is its own Flutterwave biller, so an unknown one is refused
            # here rather than vended on another disco's item.
            product = catalog.CATALOG.product(kind, provider)
            if product is None:
                raise ApiError(400, "unsupported_product",
                               f"I can't find {provider} for {kind}.")
            if product.needs_plan:
                if not plan:
                    raise ApiError(400, "plan_required", "Choose a plan first.")
                chosen = catalog.CATALOG.plan(product, plan)
                if chosen is None:
                    raise ApiError(400, "unknown_plan",
                                   f"No '{plan}' plan for {product.name}.")
                plan_price = chosen.price_ngn
            else:
                plan = None
        else:
            # Internet and water are not sold through Flutterwave here; the bill can
            # be saved, but paying it will refuse and charge nothing.
            plan = None

        bills = self.bills(account_id)
        if any(b["kind"] == kind and b["reference"] == reference for b in bills.values()):
            raise ApiError(409, "duplicate_bill", "That bill is already saved.")

        bill: dict[str, Any] = {
            "id": f"bill_{uuid.uuid4().hex[:8]}",
            "kind": kind,
            "provider": provider,
            "label": label,
            "reference": reference,
            "last_amount_ngn": None,
            "last_units": None,
            "last_paid_at": None,
        }
        if plan:
            bill["plan"] = plan
        if plan_price is not None:
            bill["plan_price_ngn"] = plan_price
        if renews_on:
            bill["renews_on"] = renews_on
        bills[bill["id"]] = bill
        self.repository.save_bill(account_id, bill)
        self.accounts.rebuild_limits(account_id)
        return bill

    def update(self, account_id: str, bill_id: str, dto: UpdateBillDto) -> dict[str, Any]:
        bill = self.get(account_id, bill_id)
        sent = dto.model_fields_set
        if "label" in sent:
            bill["label"] = self._name(dto.label or "", "label", LABEL_MAX)
        if "plan" in sent:
            if bill["kind"] not in PLAN_KINDS:
                raise ApiError(400, "bad_bill", "Only data and TV bills have plans.")
            product = catalog.CATALOG.product(bill["kind"], bill["provider"])
            if product is None:
                raise ApiError(400, "unsupported_product", "That provider has no plans.")
            code = (dto.plan or "").strip()
            chosen = catalog.CATALOG.plan(product, code) if code else None
            if chosen is None:
                raise ApiError(400, "unknown_plan", f"No '{code}' plan for {product.name}.")
            bill["plan"] = chosen.code
            bill["plan_price_ngn"] = chosen.price_ngn
        if "renews_on" in sent:
            # Repairing the calendar is the point of the field: set it to a date, or
            # clear it with "" / null for a bill that does not renew on a cycle.
            raw_date = (dto.renews_on or "").strip()
            if raw_date:
                bill["renews_on"] = self._renews_on(raw_date)
            else:
                bill.pop("renews_on", None)
        self.repository.save_bill(account_id, bill)
        return bill

    def confirm(self, account_id: str, bill_id: str) -> dict[str, Any]:
        """The owner, signed in, agrees to a bill the agent saved. Only now does its
        reference join the meters Stark (and the vault) may pay."""
        bill = self.get(account_id, bill_id)
        if bill.pop("needs_confirmation", None):
            self.repository.save_bill(account_id, bill)
            self.accounts.rebuild_limits(account_id)
        return bill

    def delete(self, account_id: str, bill_id: str) -> dict[str, Any]:
        bills = self.bills(account_id)
        if bill_id not in bills:
            raise ApiError(404, "unknown_bill", f"No bill {bill_id}")
        if self.receipts.has_pending(account_id, bill_id):
            raise ApiError(409, "bill_in_flight",
                           "That bill has a payment still in flight. Try again after it settles.")
        del bills[bill_id]
        self.repository.delete_bill(account_id, bill_id)
        self.accounts.rebuild_limits(account_id)
        return {"deleted": True, "bill_id": bill_id}

    def apply_delivery(self, account_id: str, receipt: dict[str, Any]) -> None:
        """Point the bill at a delivered payment: its last top-up and the units it bought.

        `spent_ngn` is moved by the receipt store, and units left are worked out
        from the receipts themselves (`TelemetryService.meter_reading`).
        """
        bill_id = receipt.get("bill_id")
        if not isinstance(bill_id, str):
            return
        bill = self.bills(account_id).get(bill_id)
        if bill is None:
            return
        bill["last_amount_ngn"] = receipt["amount_ngn"]
        bill["last_units"] = receipt.get("units")
        bill["last_paid_at"] = receipt["created_at"]
        self.repository.save_bill(account_id, bill)

    @staticmethod
    def _name(raw: str, field: str, longest: int) -> str:
        """Refused, not trimmed: a name cut short or stripped of characters would be
        saved as something the owner never typed. Only new writes are checked."""
        name = re.sub(r"\s+", " ", raw).strip()
        if not name:
            raise ApiError(400, "bad_bill", f"{field} is required")
        if len(name) > longest:
            raise ApiError(400, "bad_bill", f"{field} must be at most {longest} characters")
        if not _NAME.fullmatch(name):
            raise ApiError(400, "bad_bill",
                           f"{field} may use letters, numbers, spaces and - ' . , & ( ) /")
        return name

    @staticmethod
    def _renews_on(raw: str) -> str:
        day = reminders.parse_date(raw)
        if day is None:
            raise ApiError(400, "bad_renews_on", "renews_on must be a date like 2026-11-03.")
        return day.isoformat()
