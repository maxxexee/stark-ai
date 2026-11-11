"""Every priced data and TV plan, straight from Flutterwave's live catalogue."""

from __future__ import annotations

from typing import Any

from app.common.api_error import ApiError
from app.modules.bill.bill_kind import PLAN_KINDS
from app.modules.vending import catalog


class PlanService:
    @staticmethod
    def plans(kind: str, provider: str) -> list[dict[str, Any]]:
        kind = kind.strip().lower()
        if kind and kind not in PLAN_KINDS:
            raise ApiError(400, "bad_kind", "Plans exist only for data and TV.")
        wanted = catalog.ALIASES.get(catalog.slug(provider), catalog.slug(provider))
        rows: list[dict[str, Any]] = []
        for each_kind in ([kind] if kind else list(PLAN_KINDS)):
            for product in catalog.CATALOG.products(each_kind):
                # Loosely: "mtn" must find MTN's data biller, the way a picker's
                # provider chip does.
                if wanted and wanted not in (catalog.slug(product.name),
                                             catalog.slug(product.biller_code)):
                    continue
                for plan in catalog.CATALOG.plans(product):
                    rows.append({
                        "kind": each_kind,
                        "provider": product.name,
                        "service_name": product.name,
                        "plan": plan.code,
                        "label": plan.name,
                        "price_ngn": plan.price_ngn,
                    })
        rows.sort(key=lambda row: (row["kind"], row["provider"], row["price_ngn"]))
        return rows
