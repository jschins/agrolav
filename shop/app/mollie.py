"""Mollie hosted checkout. Card numbers stay on Mollie's page."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import httpx


def euro_value(amount_cents: int) -> str:
    value = (Decimal(amount_cents) / Decimal(100)).quantize(Decimal("0.01"))
    return format(value, "f")


def payment_payload(
    *,
    amount_cents: int,
    description: str,
    redirect_url: str,
    webhook_url: str,
    order_id: str,
) -> dict[str, object]:
    return {
        "amount": {"currency": "EUR", "value": euro_value(amount_cents)},
        "description": description[:255],
        "redirectUrl": redirect_url,
        "webhookUrl": webhook_url,
        "metadata": {"order_id": order_id},
    }


@dataclass(frozen=True)
class Payment:
    id: str
    status: str
    amount_cents: int
    order_id: str


class MollieClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def create_payment(
        self,
        *,
        order_id: str,
        amount_cents: int,
        description: str,
        redirect_url: str,
        webhook_url: str,
    ) -> tuple[str, str]:
        payload = payment_payload(
            amount_cents=amount_cents,
            description=description,
            redirect_url=redirect_url,
            webhook_url=webhook_url,
            order_id=order_id,
        )
        response = httpx.post(
            "https://api.mollie.com/v2/payments",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        return str(data["id"]), str(data["_links"]["checkout"]["href"])

    def fetch(self, payment_id: str) -> Payment:
        response = httpx.get(
            f"https://api.mollie.com/v2/payments/{payment_id}",
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=20,
        )
        response.raise_for_status()
        return payment_from_api(response.json())


class DevMollie:
    """Local stand-in used only when no Mollie API key is configured."""

    def __init__(self, public_base_url: str) -> None:
        self.public_base_url = public_base_url.rstrip("/")
        self._payments: dict[str, Payment] = {}

    def create_payment(
        self,
        *,
        order_id: str,
        amount_cents: int,
        description: str,
        redirect_url: str,
        webhook_url: str,
    ) -> tuple[str, str]:
        del description, redirect_url, webhook_url
        payment_id = f"tr_dev_{order_id}"
        self._payments[payment_id] = Payment(
            id=payment_id,
            status="open",
            amount_cents=amount_cents,
            order_id=order_id,
        )
        return payment_id, f"{self.public_base_url}/dev/betalen/{payment_id}"

    def fetch(self, payment_id: str) -> Payment:
        return self._payments[payment_id]

    def mark(self, payment_id: str, status: str) -> None:
        current = self._payments[payment_id]
        self._payments[payment_id] = Payment(
            id=current.id,
            status=status,
            amount_cents=current.amount_cents,
            order_id=current.order_id,
        )


def payment_from_api(data: dict[str, object]) -> Payment:
    amount = data.get("amount")
    if not isinstance(amount, dict):
        raise ValueError("Mollie payment has no amount")
    value = Decimal(str(amount.get("value")))
    cents = int((value * 100).quantize(Decimal("1")))
    metadata = data.get("metadata") or {}
    order_id = ""
    if isinstance(metadata, dict):
        order_id = str(metadata.get("order_id") or "")
    return Payment(
        id=str(data["id"]),
        status=str(data["status"]),
        amount_cents=cents,
        order_id=order_id,
    )
