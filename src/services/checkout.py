import hashlib
import os

from pydantic import HttpUrl, TypeAdapter, ValidationError
from sqlalchemy import select
from stripe import StripeClient, StripeError, RequestsClient

from src.core.errors import CheckoutUnavailable, MeteringError
from src.db.database import SessionLocal
from src.db.db_models import Subscription, Tenant
from src.schemas.models import CheckoutResponse


def create_checkout(tenant_id: int, idempotency_key: str) -> CheckoutResponse:
    """Create test Checkout without granting subscription access."""
    if not idempotency_key.strip():
        raise MeteringError(422, "A nonempty idempotency key is required.")
    try:
        secret = os.environ["STRIPE_SECRET_KEY"]
        price_id = os.environ["STRIPE_PRO_PRICE_ID"]
        success_url = os.environ["STRIPE_CHECKOUT_SUCCESS_URL"]
        cancel_url = os.environ["STRIPE_CHECKOUT_CANCEL_URL"]
        for url in (success_url, cancel_url):
            TypeAdapter(HttpUrl).validate_python(url)
        if not secret.startswith("sk_test_") or not price_id.startswith("price_"):
            raise ValueError
    except (KeyError, ValueError, ValidationError):
        raise CheckoutUnavailable("Stripe test Checkout configuration is missing or invalid.") from None

    client = StripeClient(secret, http_client=RequestsClient(timeout=10), max_network_retries=1)
    try:
        price = client.v1.prices.retrieve(price_id).to_dict()
        recurring = price.get("recurring") or {}
        if (price.get("livemode") is not False or not price.get("active")
                or price.get("currency") != "usd" or price.get("unit_amount") != 2000
                or price.get("billing_scheme") != "per_unit"
                or recurring.get("interval") != "month" or recurring.get("interval_count") != 1
                or recurring.get("usage_type") != "licensed"):
            raise CheckoutUnavailable("Pro price must be an active test price of 20 USD per month.")

        with SessionLocal.begin() as session:
            tenant = session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
            if tenant is None:
                raise MeteringError(404, "Tenant not found.")
            subscription = session.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
            if subscription is not None and subscription.stripe_subscription_id and subscription.status not in (
                "canceled", "incomplete_expired",
            ):
                raise MeteringError(409, "Tenant already has a Stripe subscription.")
            identity = f"{tenant.id}:{tenant.created_at.isoformat()}"
            customer_key = hashlib.sha256(identity.encode()).hexdigest()
            if tenant.stripe_customer_id is None:
                customer = client.v1.customers.create(
                    {"metadata": {"tenant_id": str(tenant.id)}},
                    options={"idempotency_key": f"capstone-customer-{customer_key}"},
                )
                tenant.stripe_customer_id = customer.id

            # Stripe may already have completed Checkout before local webhook sync.
            subscriptions = client.v1.subscriptions.list({"customer": tenant.stripe_customer_id, "status": "all"})
            if any(item.status not in ("canceled", "incomplete_expired")
                   for item in subscriptions.auto_paging_iter()):
                raise MeteringError(409, "Tenant already has a Stripe subscription.")
            sessions = client.v1.checkout.sessions.list({"customer": tenant.stripe_customer_id, "status": "open"})
            checkout = next((item for item in sessions.auto_paging_iter()
                             if item.metadata.to_dict().get("tenant_id") == str(tenant.id)
                             and item.metadata.to_dict().get("price_id") == price_id), None)
            if checkout is None:
                request_key = hashlib.sha256(f"{identity}:{idempotency_key}".encode()).hexdigest()
                checkout = client.v1.checkout.sessions.create({
                    "mode": "subscription", "customer": tenant.stripe_customer_id,
                    "line_items": [{"price": price_id, "quantity": 1}],
                    "client_reference_id": str(tenant.id),
                    "metadata": {"tenant_id": str(tenant.id), "price_id": price_id},
                    "subscription_data": {"metadata": {"tenant_id": str(tenant.id)}},
                    "success_url": success_url, "cancel_url": cancel_url,
                }, options={"idempotency_key": f"capstone-checkout-{request_key}"})
            if not checkout.url:
                raise CheckoutUnavailable("Stripe Checkout URL is unavailable.")
            result = CheckoutResponse(checkout_url=checkout.url)
        return result
    except StripeError:
        raise CheckoutUnavailable("Stripe Checkout is temporarily unavailable.") from None
