"""
check_stripe.py -- Verify the Stripe setup before a customer finds a problem.

    .venv\\Scripts\\python.exe check_stripe.py

Talks to Stripe with your configured key and checks the things that actually go
wrong: a product ID pasted where a price ID belongs, a one-off price instead of
a recurring one, test keys with live prices, a webhook pointing at the wrong URL
or missing the subscription events, and a price label that disagrees with what
the customer is really charged.

Read-only. It never creates, modifies or deletes anything in your account.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.app.config import settings  # noqa: E402

PROBLEMS: list = []
NOTES: list = []


def ok(message: str) -> None:
    print(f"  [ok  ] {message}")


def bad(message: str, fix: str = "") -> None:
    print(f"  [FAIL] {message}")
    if fix:
        print(f"         -> {fix}")
    PROBLEMS.append(message)


def note(message: str) -> None:
    print(f"  [note] {message}")
    NOTES.append(message)


def money(amount: int | None, currency: str) -> str:
    if amount is None:
        return "metered/variable"
    symbol = {"usd": "$", "gbp": "£", "eur": "€"}.get(currency.lower(), "")
    return f"{symbol}{amount / 100:.2f} {currency.upper()}"


print("\nStripe configuration check")
print("=" * 62)

# --------------------------------------------------------------- keys ---- #
print("\nKeys")
if not settings.stripe_secret_key:
    bad("STRIPE_SECRET_KEY is not set",
        "Dashboard > Developers > API keys. Use sk_test_... while testing.")
    print("\nNothing else can be checked without a key.")
    print("=" * 62)
    print("Payments are OFF. Everyone stays on the free plan.")
    sys.exit(1)

key = settings.stripe_secret_key
live_mode = key.startswith("sk_live_")
if not key.startswith(("sk_test_", "sk_live_")):
    bad(f"STRIPE_SECRET_KEY looks wrong (starts {key[:8]!r})",
        "It should start sk_test_ or sk_live_. A pk_... key is the publishable "
        "one and will not work here.")
else:
    ok(f"Secret key present ({'LIVE' if live_mode else 'test'} mode)")

try:
    import stripe
except ImportError:
    bad("The stripe package is not installed",
        ".venv\\Scripts\\python.exe -m pip install stripe")
    sys.exit(1)

stripe.api_key = key

try:
    account = stripe.Account.retrieve()
    name = account.get("business_profile", {}).get("name") or account.get("id")
    ok(f"Key works, account: {name}")
    if live_mode and not account.get("charges_enabled"):
        bad("This live account cannot take charges yet",
            "Finish Stripe's account activation before going live.")
except Exception as exc:  # noqa: BLE001
    bad(f"Stripe rejected the key: {str(exc)[:120]}",
        "Copy it again from Developers > API keys.")
    sys.exit(1)

# ------------------------------------------------------------- prices ---- #
print("\nPrices")
wanted = {
    "Starter": (settings.stripe_price_starter, settings.price_label_starter),
    "Pro": (settings.stripe_price_pro, settings.price_label_pro),
}

for tier, (price_id, label) in wanted.items():
    if not price_id:
        bad(f"{tier}: no price ID set",
            f"Create a recurring monthly price, then set "
            f"STRIPE_PRICE_{tier.upper()} to its price_... ID.")
        continue

    if price_id.startswith("prod_"):
        bad(f"{tier}: that is a PRODUCT id, not a price id",
            "Open the product in Stripe and copy the price_... ID underneath it.")
        continue
    if not price_id.startswith("price_"):
        bad(f"{tier}: {price_id!r} is not a price id",
            "It should start with price_.")
        continue

    try:
        price = stripe.Price.retrieve(price_id)
    except Exception as exc:  # noqa: BLE001
        bad(f"{tier}: Stripe cannot find {price_id}",
            "Check for a typo, or whether it belongs to the other mode "
            "(test prices do not exist in live mode, and vice versa). "
            f"[{str(exc)[:80]}]")
        continue

    if not price.get("active"):
        bad(f"{tier}: that price is archived", "Create a new one and use its ID.")

    recurring = price.get("recurring")
    if not recurring:
        bad(f"{tier}: that price is one-off, not a subscription",
            "Recreate it as 'Recurring'. Checkout runs in subscription mode "
            "and will reject a one-off price.")
    elif recurring.get("interval") != "month":
        note(f"{tier}: bills every {recurring.get('interval_count', 1)} "
             f"{recurring.get('interval')}, not monthly. Fine if deliberate; "
             "the app describes plans as monthly.")

    real = money(price.get("unit_amount"), price.get("currency", ""))
    ok(f"{tier}: {price_id} = {real}")

    # The label is only a display string, so it can silently disagree with what
    # is actually charged -- in the amount OR the currency. Getting the currency
    # wrong is the easier mistake and the more damaging one: "$12" against a
    # GBP price means the customer is quoted one thing and billed another.
    currency = price.get("currency", "").lower()
    digits = "".join(c for c in label if c.isdigit() or c == ".")
    amount_ok = True
    if price.get("unit_amount") is not None and digits:
        shown = float(digits)
        charged = price["unit_amount"] / 100
        if abs(shown - charged) > 0.005:
            amount_ok = False
            bad(f"{tier}: the app shows {label!r} but Stripe charges {real}",
                f"Set PRICE_LABEL_{tier.upper()} to match, or fix the price.")

    symbols = {"usd": "$", "gbp": "£", "eur": "€"}
    expected_symbol = symbols.get(currency)
    wrong_symbols = [s for c, s in symbols.items()
                     if c != currency and s in label]
    if expected_symbol and expected_symbol not in label and wrong_symbols:
        bad(f"{tier}: label says {label!r} but the price is in "
            f"{currency.upper()}",
            f"A customer would be quoted {wrong_symbols[0]} and charged "
            f"{expected_symbol}. Set PRICE_LABEL_{tier.upper()} to "
            f"'{expected_symbol}{price['unit_amount'] / 100:.0f}/mo'.")
    elif expected_symbol and expected_symbol not in label:
        note(f"{tier}: label {label!r} shows no currency; the price is "
             f"{currency.upper()}.")
    elif amount_ok:
        ok(f"{tier}: displayed label {label!r} matches")

# ------------------------------------------------------------ webhook ---- #
print("\nWebhook")
expected_url = f"{settings.public_url.rstrip('/')}/api/billing/webhook"
needed_events = {
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}

if not settings.stripe_webhook_secret:
    bad("STRIPE_WEBHOOK_SECRET is not set",
        "Without it every webhook is rejected, so nobody's plan will ever "
        "upgrade even after they pay. Developers > Webhooks > your endpoint > "
        "Signing secret (whsec_...).")
elif not settings.stripe_webhook_secret.startswith("whsec_"):
    bad("STRIPE_WEBHOOK_SECRET does not look like a signing secret",
        "It should start whsec_.")
else:
    ok("Signing secret present")

if "localhost" in expected_url or "127.0.0.1" in expected_url:
    note(f"PUBLIC_URL is local ({settings.public_url}). Stripe cannot reach "
         "this machine, so for local testing run:\n"
         "         stripe listen --forward-to "
         "localhost:8000/api/billing/webhook\n"
         "         and use the whsec_ it prints.")
else:
    try:
        endpoints = stripe.WebhookEndpoint.list(limit=100).get("data", [])
        match = next((e for e in endpoints if e.get("url") == expected_url), None)
        if match is None:
            urls = ", ".join(e.get("url", "?") for e in endpoints) or "none"
            bad(f"No webhook endpoint points at {expected_url}",
                f"Add one in Developers > Webhooks. Currently configured: {urls}")
        else:
            ok(f"Endpoint exists: {expected_url}")
            listening = set(match.get("enabled_events") or [])
            missing = needed_events - listening
            if "*" in listening:
                ok("Listening to all events")
            elif missing:
                bad(f"Endpoint is missing events: {', '.join(sorted(missing))}",
                    "Without these a payment never upgrades the account.")
            else:
                ok("Subscribed to the three subscription events")
            if match.get("status") != "enabled":
                bad(f"Endpoint is {match.get('status')}", "Enable it in Stripe.")
    except Exception as exc:  # noqa: BLE001
        note(f"Could not list webhook endpoints: {str(exc)[:90]}")

# -------------------------------------------------------------- ready ---- #
print("\n" + "=" * 62)
if PROBLEMS:
    print(f"NOT READY - {len(PROBLEMS)} problem(s) above.")
    sys.exit(1)

print("Stripe is configured. Customers can subscribe.")
if live_mode:
    print("You are in LIVE mode: real cards will be charged.")
else:
    print("Test mode. Pay with card 4242 4242 4242 4242, any future expiry.")
if NOTES:
    print(f"({len(NOTES)} note(s) above worth reading.)")
sys.exit(0)
