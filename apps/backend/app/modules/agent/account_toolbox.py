"""The agent's view of one account. Deliberately thin: it may read state and pay a
bill, and nothing else."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.common.api_error import ApiError
from app.modules.agent import agent as agent_layer

if TYPE_CHECKING:
    from app.app_module import AppModule


class AccountToolbox:
    def __init__(self, account_id: str, module: "AppModule") -> None:
        self.account_id = account_id
        self.module = module

    def get_state(self) -> dict:
        return self.module.state.snapshot(self.account_id)

    def list_bills(self) -> list[dict]:
        return list(self.module.bills.bills(self.account_id).values())

    def recent_activity(self) -> list[dict]:
        return self.module.bill_payments.recent(self.account_id, 20)

    def request_approval(self, bill_id: str, amount_ngn: int, reason: str) -> dict:
        bill = self.module.bills.get(self.account_id, bill_id)
        request = self.module.approvals.request(self.account_id, bill, amount_ngn, reason)
        return {**request,
                "window_minutes": self.module.approvals.window_minutes(self.account_id)}

    def record_refusal(self, bill_id: str, amount_ngn: int, reason: str) -> None:
        bill = self.module.bills.get(self.account_id, bill_id)
        self.module.bill_payments.record_declined(self.account_id, bill_id, bill["label"],
                                                  amount_ngn, reason)

    def pay(self, bill_id: str, amount_ngn: int) -> dict:
        try:
            return self.module.bill_payments.pay(self.account_id, bill_id, amount_ngn)
        except ApiError as err:
            raise agent_layer.PaymentError(err.code, err.message, err.detail) from err
