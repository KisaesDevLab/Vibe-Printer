"""Turn a Stripe Charge / PaymentIntent into a Vibe Print job.

Maps a Stripe `charge.succeeded` (or `payment_intent.succeeded` with a charge) object to the
`data` shape used by the "Stripe Payment Receipt" format (thermal) or "(PDF)" template (office),
then enqueues a print.

    # thermal receipt printer using the saved format
    python examples/stripe_to_vibe.py URL SECRET --printer 1 --format 2 < charge.json

    # office/laser (CUPS or IPP) using the PDF template
    python examples/stripe_to_vibe.py URL SECRET --printer 4 --template 1 < charge.json

`charge.json` is the Stripe Charge object (event["data"]["object"], or stripe.Charge.retrieve).
Line items aren't on a Stripe Charge — pass them from your order system via --line-items.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime

import httpx


def charge_to_data(ch: dict, line_items: list[dict] | None = None) -> dict:
    cents = ch.get("amount_captured") or ch.get("amount") or 0
    card = (ch.get("payment_method_details") or {}).get("card") or {}
    billing = ch.get("billing_details") or {}
    created = ch.get("created")
    when = (
        datetime.fromtimestamp(created, UTC).strftime("%Y-%m-%d %H:%M")
        if isinstance(created, int)
        else ""
    )
    return {
        "merchant": ch.get("statement_descriptor") or "Your Store",
        "date": when,
        "amount": f"{cents / 100:.2f}",
        "currency": (ch.get("currency") or "usd").upper(),
        "card_brand": (card.get("brand") or "card").title(),
        "card_last4": card.get("last4") or "",
        "status": (ch.get("status") or "").upper(),
        "receipt_number": ch.get("receipt_number") or "",
        "charge_id": ch.get("id") or "",
        "customer_email": ch.get("receipt_email") or billing.get("email") or "",
        "receipt_url": ch.get("receipt_url") or "",
        "line_items": line_items or [],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("secret")
    ap.add_argument("--printer", type=int, required=True)
    ap.add_argument("--format", type=int)
    ap.add_argument("--template", type=int)
    ap.add_argument("--line-items", help="JSON list of {name, amount} (formatted strings)")
    args = ap.parse_args()

    charge = json.load(sys.stdin)
    # Accept a full event too: {"data": {"object": {...}}}
    if "data" in charge and isinstance(charge["data"], dict):
        charge = charge["data"].get("object", charge)

    line_items = json.loads(args.line_items) if args.line_items else None
    data = charge_to_data(charge, line_items)

    body: dict = {"printer": args.printer, "data": data}
    if args.template:
        body["template"] = args.template
    elif args.format:
        body["format"] = args.format

    headers = {"Authorization": f"Bearer {args.secret}", "Idempotency-Key": uuid.uuid4().hex}
    r = httpx.post(f"{args.base_url}/v1/print", json=body, headers=headers, timeout=15)
    print(r.status_code, r.text)


if __name__ == "__main__":
    main()
