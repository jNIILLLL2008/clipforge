"""
billing.py -- Stripe subscriptions.

Checkout and the customer portal are both hosted by Stripe, so no card details
ever reach this service. Plan changes are applied from the **webhook**, never
from the browser redirect: a user returning to a success URL proves nothing,
whereas a signed webhook does.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import settings
from ..db import get_db
from ..logging_setup import get_logger
from ..models import Plan, User, utcnow

log = get_logger("billing")
router = APIRouter(prefix="/api/billing")


def _stripe():
    if not settings.billing_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Billing is not configured on this deployment.")
    try:
        import stripe
    except ImportError as exc:  # pragma: no cover - dependency is optional
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "The stripe package is not installed.") from exc
    stripe.api_key = settings.stripe_secret_key
    return stripe


PRICE_FOR = {
    Plan.STARTER: lambda: settings.stripe_price_starter,
    Plan.PRO: lambda: settings.stripe_price_pro,
}


def _plan_for_price(price_id: str) -> Optional[Plan]:
    if price_id and price_id == settings.stripe_price_starter:
        return Plan.STARTER
    if price_id and price_id == settings.stripe_price_pro:
        return Plan.PRO
    return None


@router.post("/checkout")
def checkout(plan: str, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    stripe = _stripe()
    try:
        wanted = Plan(plan)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown plan.")
    if wanted not in PRICE_FOR:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "That plan cannot be purchased.")
    price = PRICE_FOR[wanted]()
    if not price:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"No Stripe price configured for {plan}.")

    if not user.stripe_customer_id:
        customer = stripe.Customer.create(email=user.email,
                                          metadata={"user_id": str(user.id)})
        user.stripe_customer_id = customer.id
        db.commit()

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=user.stripe_customer_id,
        line_items=[{"price": price, "quantity": 1}],
        success_url=f"{settings.public_url}/?billing=success",
        cancel_url=f"{settings.public_url}/?billing=cancelled",
        # Lets the webhook identify the account without trusting the browser.
        subscription_data={"metadata": {"user_id": str(user.id)}},
        allow_promotion_codes=True,
    )
    return {"url": session.url}


@router.post("/portal")
def portal(user: User = Depends(current_user)):
    stripe = _stripe()
    if not user.stripe_customer_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "No subscription to manage yet.")
    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=settings.public_url,
    )
    return {"url": session.url}


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    """Apply plan changes. This is the only place a plan is trusted from."""
    stripe = _stripe()
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    if not settings.stripe_webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "STRIPE_WEBHOOK_SECRET is not set.")
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, settings.stripe_webhook_secret
        )
    except Exception as exc:  # noqa: BLE001 - any failure means "not from Stripe"
        log.warning("Rejected webhook: %s", exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bad signature.")

    kind = event["type"]
    obj = event["data"]["object"]

    if kind in {"customer.subscription.created", "customer.subscription.updated"}:
        _apply_subscription(db, obj)
    elif kind == "customer.subscription.deleted":
        _downgrade(db, obj)
    else:
        log.debug("Ignoring webhook %s", kind)

    return {"received": True}


def _find_user(db: Session, obj: dict) -> Optional[User]:
    user_id = (obj.get("metadata") or {}).get("user_id")
    if user_id:
        user = db.get(User, int(user_id))
        if user:
            return user
    customer = obj.get("customer")
    if customer:
        return (db.query(User)
                .filter(User.stripe_customer_id == customer).one_or_none())
    return None


def _apply_subscription(db: Session, obj: dict) -> None:
    user = _find_user(db, obj)
    if not user:
        log.warning("Subscription webhook for an unknown customer.")
        return

    items = (obj.get("items") or {}).get("data") or []
    price_id = items[0]["price"]["id"] if items else ""
    plan = _plan_for_price(price_id)
    active = obj.get("status") in {"active", "trialing"}

    if plan and active:
        if user.plan != plan:
            log.info("User %s -> %s", user.id, plan.value)
        user.plan = plan
        user.stripe_subscription_id = obj.get("id")
        # A new paid period is a fresh allowance.
        user.period_started_at = utcnow()
        user.renders_this_period = 0
    elif not active:
        user.plan = Plan.FREE
    db.commit()


def _downgrade(db: Session, obj: dict) -> None:
    user = _find_user(db, obj)
    if not user:
        return
    log.info("Subscription ended for user %s.", user.id)
    user.plan = Plan.FREE
    user.stripe_subscription_id = None
    db.commit()
