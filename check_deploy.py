"""
check_deploy.py -- Is this instance safe to put in front of paying customers?

    .venv\\Scripts\\python.exe check_deploy.py

Checks the things that are silent failures rather than crashes: a development
signing key that would let anyone forge a session, SQLite under concurrent
writers, a storage directory that vanishes on redeploy, OAuth redirects still
pointing at localhost, and payment settings that only half work.

Read-only. Run it against the live configuration before you announce anything.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.app.config import DEV_SECRET, settings  # noqa: E402

BLOCKERS: list = []
WARNINGS: list = []


def ok(msg: str) -> None:
    print(f"  [ok   ] {msg}")


def blocker(msg: str, fix: str = "") -> None:
    print(f"  [STOP ] {msg}")
    if fix:
        print(f"          -> {fix}")
    BLOCKERS.append(msg)


def warn(msg: str, fix: str = "") -> None:
    print(f"  [warn ] {msg}")
    if fix:
        print(f"          -> {fix}")
    WARNINGS.append(msg)


    # --url checks a running deployment from the outside instead.
if "--url" in sys.argv:
    import json
    import urllib.request

    try:
        target = sys.argv[sys.argv.index("--url") + 1].rstrip("/")
    except IndexError:
        sys.exit("Usage: check_deploy.py --url https://your-app.up.railway.app")

    print(f"\nChecking the LIVE deployment at {target}")
    print("=" * 64)

    if not target.startswith("https://"):
        warn("Not HTTPS", "Cookies and OAuth tokens would travel in clear text.")
    try:
        with urllib.request.urlopen(f"{target}/api/health", timeout=20) as r:
            health = json.load(r)
        ok(f"Responding: env={health.get('env')} billing={health.get('billing')}")
        if health.get("env") != "production":
            blocker(f"The live instance reports ENV={health.get('env')}",
                    "Set ENV=production in the platform's variables.")
        if not health.get("billing"):
            warn("The live instance has no Stripe key",
                 "Nobody can subscribe there yet.")
        sources = health.get("sources") or []
        ok(f"Sources enabled: {', '.join(sources) or 'none'}")
    except Exception as exc:  # noqa: BLE001
        blocker(f"Could not reach {target}/api/health: {str(exc)[:90]}",
                "Is the deploy finished and the domain generated?")

    for path, label in (("/", "landing page"), ("/app", "the studio")):
        try:
            with urllib.request.urlopen(target + path, timeout=20) as r:
                ok(f"{label} responds ({r.status})")
        except Exception as exc:  # noqa: BLE001
            blocker(f"{label} failed: {str(exc)[:70]}")

    print("\n" + "=" * 64)
    if BLOCKERS:
        print(f"LIVE SITE HAS PROBLEMS - {len(BLOCKERS)} blocker(s).")
        sys.exit(1)
    print(f"Live site looks healthy. {len(WARNINGS)} warning(s).")
    print("Note: settings the outside cannot see (SECRET_KEY, the database,")
    print("the volume) are only checked by running this INSIDE the container.")
    sys.exit(0)


print("\nDeployment readiness")
print("=" * 64)
production = settings.env == "production"
print(f"  Checking: THIS MACHINE (config from .env), not any deployment.")
print(f"  ENV={settings.env}  DEBUG={settings.debug}")
if settings.env != "production":
    print("  A development result here is expected and fine. To check what")
    print("  you actually deployed, use:  check_deploy.py --url https://...")

# ------------------------------------------------------------ security --- #
print("\nSecurity")
if settings.secret_key in ("", DEV_SECRET) or settings.secret_key.startswith("local-dev"):
    blocker("SECRET_KEY is a development value",
            "Anyone could forge a login token. Generate one with:\n"
            "             python -c \"import secrets;print(secrets.token_urlsafe(32))\"")
else:
    ok("SECRET_KEY is set to a real value")

if settings.debug and production:
    blocker("DEBUG is on in production", "Set DEBUG=false.")
elif settings.debug:
    warn("DEBUG is on", "Fine locally; must be off in production.")
else:
    ok("DEBUG is off")

if settings.public_url.startswith("http://") and "localhost" not in settings.public_url \
        and "127.0.0.1" not in settings.public_url:
    blocker(f"PUBLIC_URL is plain HTTP ({settings.public_url})",
            "Session cookies and OAuth tokens would travel in clear text. "
            "Use https://.")
elif "localhost" in settings.public_url or "127.0.0.1" in settings.public_url:
    warn(f"PUBLIC_URL is still local ({settings.public_url})",
         "Set it to your real domain, or Stripe redirects and the YouTube "
         "callback will send users to their own machine.")
else:
    ok(f"PUBLIC_URL is {settings.public_url}")

if "*" in settings.cors_origins:
    warn("CORS allows any origin", "List your own domain instead.")

# ------------------------------------------------------------- storage --- #
print("\nData")
if settings.database_url.startswith("sqlite"):
    message = "DATABASE_URL is SQLite"
    fix = ("SQLite locks the whole file on write, and this app writes from the "
           "web process and the render workers at once. Use Postgres:\n"
           "             postgresql+psycopg://user:pass@host/clipforge")
    blocker(message, fix) if production else warn(message, fix)
else:
    ok("Database is not SQLite")
    try:
        import psycopg  # noqa: F401
        ok("Postgres driver installed")
    except ImportError:
        blocker("psycopg is not installed",
                "pip install 'psycopg[binary]'")

storage = Path(settings.storage_dir)
if not storage.exists():
    warn(f"Storage directory does not exist yet ({storage})")
else:
    ok(f"Storage at {storage}")
try:
    usage = shutil.disk_usage(storage if storage.exists() else Path.cwd())
    free_gb = usage.free / 1024 ** 3
    line = f"{free_gb:.1f} GB free on the storage disk"
    # A single render is 40-80 MB and nothing is cleaned up automatically.
    (ok if free_gb >= 20 else warn)(line)
    if free_gb < 20:
        print("          -> renders are 40-80 MB each and are never deleted "
              "automatically. Plan a retention policy.")
except OSError:
    pass

if production:
    warn("Renders are stored on the local filesystem",
         "Fine on one box with a persistent volume. If you run more than one "
         "instance, or your host has an ephemeral disk, move to object storage "
         "or downloads will 404.")

# --------------------------------------------------------------- media --- #
print("\nMedia")
for name, binary in (("ffmpeg", settings.ffmpeg), ("ffprobe", settings.ffprobe)):
    found = shutil.which(binary) or (Path(binary).exists() and binary)
    if not found:
        blocker(f"{name} not found at {binary!r}",
                "Nothing can render without it. The Dockerfile installs it; "
                "on a VPS: apt install ffmpeg")
        continue
    try:
        out = subprocess.run([binary, "-version"], capture_output=True,
                             text=True, timeout=20).stdout.splitlines()[0]
        ok(f"{name}: {out[:56]}")
    except Exception as exc:  # noqa: BLE001
        blocker(f"{name} will not run: {exc}")

# ------------------------------------------------------------- billing --- #
print("\nBilling")
if not settings.billing_enabled:
    warn("Stripe is not configured", "Nobody can subscribe; everyone stays "
         "free. Run check_stripe.py once you have added keys.")
else:
    live = settings.stripe_secret_key.startswith("sk_live_")
    ok(f"Stripe configured ({'LIVE' if live else 'test'} mode)")
    if production and not live:
        warn("Production is using Stripe TEST keys",
             "Real cards will be declined. Swap in the live key and live "
             "price IDs when you are ready to charge.")
    if not settings.stripe_webhook_secret:
        blocker("No STRIPE_WEBHOOK_SECRET",
                "Customers would pay and never be upgraded, because the "
                "webhook is the only thing that changes a plan.")
    for tier, price in (("starter", settings.stripe_price_starter),
                        ("pro", settings.stripe_price_pro)):
        if not price:
            warn(f"No price ID for {tier}", f"That plan cannot be bought.")

# ------------------------------------------------------------- youtube --- #
print("\nPublishing")
if not settings.google_client_id:
    warn("YouTube publishing is not configured",
         "Videos still render and download; they just do not upload.")
else:
    ok("Google OAuth client configured")
    if "localhost" in settings.google_redirect_uri:
        blocker("GOOGLE_REDIRECT_URI still points at localhost",
                f"Set it to {settings.public_url}/api/youtube/callback and add "
                "that exact URL to the OAuth client in Google Cloud.")
    else:
        ok(f"Redirect URI: {settings.google_redirect_uri}")
    warn("Check your YouTube API quota before launch",
         "The default 10,000 units/day is about 6 uploads across ALL users. "
         "Daily automation for even ten subscribers exceeds it.")

# --------------------------------------------------------------- scale --- #
print("\nScale")
if settings.run_scheduler:
    ok("This instance runs the daily scheduler")
    warn("Only ONE instance may do so",
         "The scheduler lives in the web process. A second instance with "
         "RUN_SCHEDULER=true would publish some accounts twice a day.")
else:
    ok("Scheduler disabled here (another instance must run it)")
ok(f"{settings.render_workers} render worker thread(s)")

# --------------------------------------------------------------- legal --- #
# These are warnings rather than blockers on purpose. Shipping with the
# defaults is a real problem, but it is not the kind that should stop a deploy
# at 2am -- and a blocker somebody has to bypass is a blocker they learn to
# bypass.
print("\nLegal")
if settings.legal_entity.strip().lower() in ("", "clipforge"):
    warn("LEGAL_ENTITY names no real controller",
         "A privacy notice has to name the controller -- the actual person or "
         "company the contract is with. 'ClipForge' is a product name, not a "
         "legal person a regulator can act against.")
else:
    ok(f"Controller is {settings.legal_entity}")

if settings.legal_contact_email.strip().lower() in ("", "support@clipforge.app"):
    warn("LEGAL_CONTACT_EMAIL points nowhere real",
         "Data requests, complaints and copyright notices all go here. Point "
         "it at an address somebody reads.")
else:
    ok(f"Legal contact is {settings.legal_contact_email}")

if not settings.legal_jurisdiction.strip():
    warn("LEGAL_JURISDICTION is empty",
         "The terms need a governing law, and it should match where the "
         "entity above is established.")
else:
    ok(f"Governed by the law of {settings.legal_jurisdiction}")

if settings.ga_measurement_id:
    ok("Analytics is on, behind the consent notice")
    print("          -> nothing loads until a visitor accepts. Verify in "
          "DevTools that no request to googletagmanager.com is made before "
          "clicking, and that the CSP names it after.")
else:
    ok("No analytics configured, so no cookie banner is shown")

# --------------------------------------------------------------- verdict - #
print("\n" + "=" * 64)
if BLOCKERS:
    print(f"NOT READY - {len(BLOCKERS)} blocker(s), {len(WARNINGS)} warning(s).")
    sys.exit(1)
print(f"No blockers. {len(WARNINGS)} warning(s) worth reading.")
sys.exit(0)
