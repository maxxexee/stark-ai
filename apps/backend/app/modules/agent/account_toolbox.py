"""The agent's view of one account. Deliberately thin: it may read state, pay a bill,
save a bill and start adding money — the same services the app's own screens call,
so every rule they enforce holds in a chat too."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.common.api_error import ApiError
from app.modules.agent.errors import PaymentError, ToolRefusal
from app.modules.bill.dtos.create_bill_dto import CreateBillDto
from app.modules.vending import catalog

if TYPE_CHECKING:
    from app.app_module import AppModule


class AccountToolbox:
    def __init__(self, account_id: str, module: "AppModule") -> None:
        self.account_id = account_id
        self.module = module

    def get_state(self) -> dict:
        return self.module.state.snapshot(self.account_id)

    def list_bills(self) -> list[dict]:
        return self.module.bills.public(self.account_id)

    def recent_activity(self) -> list[dict]:
        return self.module.bill_payments.recent(self.account_id, 20)

    def funding(self) -> dict:
        """Which ways of adding money work, and the last few deposits — without their
        links or addresses, which only ever reach the user from `add_money`."""
        return {
            **self.module.deposits.methods(),
            "recent_deposits": [
                {key: deposit[key] for key in
                 ("method", "amount_ngn", "credited_ngn", "status", "created_at")}
                for deposit in self.module.deposits.recent(self.account_id, 3)
            ],
        }

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
            raise PaymentError(err.code, err.message, err.detail) from err

    def add_bill(self, dto: CreateBillDto) -> dict:
        try:
            return self.module.bills.add(self.account_id, dto)
        except ApiError as err:
            raise ToolRefusal(err.code, err.message) from err

    def find_plans(self, kind: str, provider: str) -> list[dict]:
        try:
            return self.module.plans.plans(kind, provider)
        except ApiError as err:
            raise ToolRefusal(err.code, err.message) from err

    def add_money(self, method: str, amount_ngn: int, asset: str, chain: str) -> dict:
        try:
            asset_id = self._asset_id(asset, chain) if method == "crypto" else None
            return self.module.deposits.start(self.account_id, amount_ngn, method, asset_id)
        except ApiError as err:
            raise ToolRefusal(err.code, err.message) from err

    def _asset_id(self, asset: str, chain: str) -> str:
        """The 1Click asset for a coin named in conversation ("USDT", "usdc on base").

        One match is the asset; none or several is a question back to the user, never
        a guess — a deposit sent on the wrong network is money they cannot get back.
        """
        listed = self.module.deposits.crypto_assets()
        if not listed:
            raise ToolRefusal(
                "not_available", "Adding money with crypto isn't set up yet.")
        symbol = asset.strip().upper()
        matches = [a for a in listed if a["symbol"].upper() == symbol]
        if not matches:
            symbols = sorted({a["symbol"].upper() for a in listed})
            raise ToolRefusal(
                "bad_asset",
                f"Stark doesn't take {asset or 'that'}. It takes {', '.join(symbols)}.")
        if chain:
            matches = [a for a in matches if catalog.slug(a["chain"]) == catalog.slug(chain)]
        if len(matches) != 1:
            chains = sorted({a["chain"] for a in listed if a["symbol"].upper() == symbol})
            raise ToolRefusal(
                "pick_chain",
                f"{symbol} can be sent on {', '.join(chains)}. Which network?")
        return matches[0]["asset_id"]
