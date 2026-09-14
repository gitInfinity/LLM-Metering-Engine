import os

from sqlalchemy import select
from stripe import RequestsClient, SignatureVerificationError, StripeClient, StripeError, Webhook

from src.core.errors import MeteringError
from src.db.database import SessionLocal
from src.db.db_models import Plan, StripeEvent, Subscription, Tenant


EVENT_TYPES = {"checkout.session.completed", "customer.subscription.created",
               "customer.subscription.updated", "customer.subscription.deleted"}


def process_webhook(payload: bytes, signature: str) -> dict:
    """Verify raw bytes and atomically sync current Stripe state with event deduplication."""
    signing_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not signing_secret.startswith("whsec_"):
        raise MeteringError(503, "Stripe webhook signing secret is not configured.")
    try:
        event = Webhook.construct_event(payload, signature, signing_secret).to_dict()
    except (ValueError, SignatureVerificationError):
        raise MeteringError(400, "Invalid Stripe webhook signature or payload.") from None
    if event.get("livemode") is not False:
        raise MeteringError(400, "Only Stripe test events are accepted.")
    event_type = event.get("type")
    if event_type not in EVENT_TYPES:
        return {"received": True}
    obj = event.get("data", {}).get("object", {})
    event_id, customer_id = event.get("id"), obj.get("customer")
    if not isinstance(event_id, str) or not event_id.startswith("evt_") or not isinstance(customer_id, str):
        raise MeteringError(400, "Invalid Stripe event identifiers.")
    if event_type == "checkout.session.completed" and obj.get("mode") != "subscription":
        return {"received": True}
    secret, price_id = os.getenv("STRIPE_SECRET_KEY", ""), os.getenv("STRIPE_PRO_PRICE_ID", "")
    if not secret.startswith("sk_test_") or not price_id.startswith("price_"):
        raise MeteringError(503, "Stripe subscription configuration is missing or invalid.")
    client = StripeClient(secret, http_client=RequestsClient(timeout=10), max_network_retries=1)
    try:
        with SessionLocal.begin() as session:
            tenant = session.scalar(select(Tenant).where(Tenant.stripe_customer_id == customer_id).with_for_update())
            if tenant is None:
                raise MeteringError(503, "Stripe customer is not linked to a local tenant.")
            if session.get(StripeEvent, event_id) is not None:
                return {"received": True}
            # Refresh after taking the lock: delayed events must not restore stale state.
            remote = client.v1.subscriptions.list({"customer": customer_id, "status": "all"})
            candidates = []
            for item in remote.auto_paging_iter():
                data = item.to_dict()
                items = data.get("items", {}).get("data", [])
                if (data.get("livemode") is False and data.get("customer") == customer_id
                        and data.get("metadata", {}).get("tenant_id") == str(tenant.id)
                        and len(items) == 1 and items[0].get("price", {}).get("id") == price_id
                        and items[0].get("quantity") == 1):
                    candidates.append(data)
            if not candidates:
                raise MeteringError(503, "Matching Stripe subscription is not available yet.")
            current = max(candidates, key=lambda item: (
                item["status"] not in ("canceled", "incomplete_expired"), item["created"], item["id"],
            ))
            plan = session.scalar(select(Plan).where(Plan.name == "Pro"))
            subscription = session.scalar(select(Subscription).where(Subscription.tenant_id == tenant.id))
            if plan is None or subscription is None:
                raise MeteringError(503, "Local subscription setup is incomplete.")
            subscription.plan_id = plan.id
            subscription.stripe_subscription_id = current["id"]
            subscription.status = current["status"]
            # Preserve signup anchor, quota windows, and all usage across plan changes.
            session.add(StripeEvent(id=event_id, event_type=event_type))
        return {"received": True}
    except StripeError:
        raise MeteringError(503, "Stripe subscription synchronization is temporarily unavailable.") from None
