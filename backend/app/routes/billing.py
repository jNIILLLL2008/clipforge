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


def _plain(obj) -> dict:
    """A real dict, all the way down.

    Objects from the Stripe SDK are not dictionaries in this version. Reading
    ``result.get("data")`` looks obviously fine and raises KeyError: 'get' --
    attribute lookup misses, __getattr__ forwards to __getitem__, and there is
    no key called "get". It took a 500 on a live purchase to find, because
    every one of these paths needs Stripe to answer before it runs.

    to_dict_recursive is the SDK's own answer and it converts nested objects
    too, which matters: a shallow dict() leaves subscription["items"] as a
    StripeObject and the next .get() fails exactly the same way.
    """
    if obj is None:
        return {}
    for name in ("to_dict_recursive", "to_dict"):
        converter = getattr(obj, name, None)
        if callable(converter):
            try:
                return dict(converter())
            except Exception:  # noqa: BLE001 - fall through to the plain cast
                pass
    try:
        return dict(obj)
    except (TypeError, ValueError):
        return {}


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

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=user.stripe_customer_id,
            line_items=[{"price": price, "quantity": 1}],
            # /app, not /. Stripe was returning paying customers to the
            # marketing page, which has no idea what ?billing=success means
            # and no sign-in state on screen -- so a completed purchase looked
            # like being thrown out of the product.
            success_url=(f"{settings.public_url}/app?billing=success"
                         "&session_id={CHECKOUT_SESSION_ID}"),
            cancel_url=f"{settings.public_url}/app?billing=cancelled",
            # Lets the webhook identify the account without trusting the browser.
            subscription_data={"metadata": {"user_id": str(user.id)}},
            allow_promotion_codes=True,
        )
    except Exception as exc:  # noqa: BLE001 - never show a customer a 500 here
        # A misconfigured price, a missing tax code, a revoked key: all of it
        # is the operator's problem, but the customer is mid-purchase. Log the
        # detail and tell them something true and brief.
        log.error("Checkout failed for user %s on %s: %s", user.id, plan, exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Checkout is temporarily unavailable. Nothing has been charged - "
            "please try again shortly.",
        ) from exc

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


@router.post("/sync")
def sync(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Re-read this account's subscription from Stripe.

    Called when somebody lands back in the app from checkout, so the plan is
    right on the first paint instead of whenever a webhook turns up.
    """
    changed = sync_from_stripe(db, user)
    return {"plan": user.plan.value, "changed": changed}


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
    # Also a Stripe object rather than a dict, and its nested "items" is
    # another one. Flatten it once here so no handler downstream has to know.
    obj = _plain(event["data"]["object"])

    if kind in {"customer.subscription.created", "customer.subscription.updated"}:
        _apply_subscription(db, obj)
    elif kind == "customer.subscription.deleted":
        _downgrade(db, obj)
    elif kind == "checkout.session.completed":
        # Belt and braces. subscription.created normally arrives too, but the
        # order is not guaranteed and an operator who subscribed only to
        # checkout events would otherwise see nothing happen at all.
        _apply_checkout(db, obj)
    else:
        log.debug("Ignoring webhook %s", kind)

    return {"received": True}


def _apply_checkout(db: Session, obj: dict) -> None:
    """A finished checkout: look the subscription up and apply it."""
    subscription_id = obj.get("subscription")
    if not subscription_id:
        return
    user = _find_user(db, obj)
    if user is None and obj.get("customer"):
        user = (db.query(User)
                  .filter(User.stripe_customer_id == obj["customer"])
                  .one_or_none())
    if user is None:
        log.warning("checkout.session.completed for an unknown customer.")
        return
    try:
        subscription = _stripe().Subscription.retrieve(subscription_id)
    except Exception as exc:  # noqa: BLE001 - a lookup failure is not fatal
        log.warning("Could not read subscription %s: %s", subscription_id, exc)
        return
    _apply_subscription(db, _plain(subscription))


def sync_from_stripe(db: Session, user: User) -> bool:
    """Ask Stripe what this customer is actually paying for, and apply it.

    Webhooks are the right mechanism and they are not a guarantee: the
    endpoint may not be registered yet, may be subscribed to the wrong events,
    or may simply arrive after the customer is already looking at the screen.
    Any of those leaves somebody who has just paid staring at "free", which is
    the worst possible moment to look broken.

    So when they come back from checkout, ask directly. Returns True when the
    plan changed.
    """
    if not user.stripe_customer_id:
        return False
    try:
        result = _stripe().Subscription.list(
            customer=user.stripe_customer_id, status="all", limit=10)
    except Exception as exc:  # noqa: BLE001 - never break the page over this
        log.warning("Could not list subscriptions for user %s: %s", user.id, exc)
        return False

    before = user.plan
    # .data, not .get("data"): see _plain. A ListObject has no .get at all.
    rows = [_plain(row) for row in (getattr(result, "data", None) or [])]
    live = [s for s in rows if s.get("status") in {"active", "trialing"}]
    if live:
        # Newest first, so an upgrade beats the subscription it replaced.
        live.sort(key=lambda s: s.get("created") or 0, reverse=True)
        _apply_subscription(db, live[0])
    else:
        log.info("No live subscription for user %s.", user.id)
    db.refresh(user)
    return user.plan != before


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
    obj = _plain(obj)
    user = _find_user(db, obj)
    if not user:
        log.warning("Subscription webhook for an unknown customer.")
        return

    items = (_plain(obj.get("items")).get("data")) or []
    first = _plain(items[0]) if items else {}
    price_id = (_plain(first.get("price")).get("id") or "") if first else ""
    plan = _plan_for_price(price_id)
    active = obj.get("status") in {"active", "trialing"}

    if active and not plan:
        # Stripe says they are paying for something this server has never
        # heard of, so nothing happens and they stay on free while being
        # charged. Almost always STRIPE_PRICE_* not matching the price the
        # checkout actually used.
        log.error(
            "User %s has an active subscription on price %r, which matches "
            "neither STRIPE_PRICE_STARTER (%r) nor STRIPE_PRICE_PRO (%r). "
            "They are being charged and left on free.",
            user.id, price_id, settings.stripe_price_starter,
            settings.stripe_price_pro)
        return

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
