import hashlib
import json

from sqlalchemy import func, select

from src.db.database import SessionLocal
from src.db.db_models import Plan, Subscription, Tenant, UsageEvent
from src.schemas.models import GenerateRequest, GenerateResponse
from src.core.errors import MeteringError
from src.core.logging import info
from src.services.pricing import PricingPolicy


def record_usage(
    tenant_id: int,
    request: GenerateRequest,
    idempotency_key: str,
) -> GenerateResponse:
    """Meter one simulated generation and commit it atomically.

    tenant_id must come from authenticated server context. Server pricing is
    loaded only for new requests, after checking for a recorded response.
    Uses PostgreSQL READ COMMITTED and owns its session/transaction. Other
    usage writers and subscription updates must acquire the same tenant lock.
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise MeteringError(422, "A nonempty idempotency key is required.")
    request = GenerateRequest.model_validate(request.model_dump())
    fingerprint = hashlib.sha256(
        json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    with SessionLocal.begin() as session:
        tenant = session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
        if tenant is None:
            raise MeteringError(404, "Tenant not found.")
        existing = session.scalar(select(UsageEvent).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.idempotency_key == idempotency_key,
        ))
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise MeteringError(409, "Idempotency key was already used for a different request.")
            info(__name__, "Returning recorded response tenant_id=%s event_id=%s", tenant_id, existing.id)
            return GenerateResponse.model_validate(existing.response_body)

        policy = PricingPolicy()
        cost = policy.cost(request.usage)

        subscription = session.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
        if subscription is None or subscription.status not in ("active", "trialing"):
            raise MeteringError(402, "An active subscription is required; update payment or subscription.")
        plan = session.get(Plan, subscription.plan_id)
        # Use the database clock after acquiring the lock, not transaction start
        # time or the application clock (see QUOTA-001).
        now = session.scalar(select(func.clock_timestamp()))
        subscription.set_quota_period(tenant.created_at, at=now)
        used_calls, used_tokens = session.execute(select(
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.input_tokens + UsageEvent.output_tokens), 0),
        ).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.created_at >= subscription.period_start,
            UsageEvent.created_at < subscription.period_end,
        )).one()
        if used_calls + 1 > plan.api_call_limit:
            raise MeteringError(429, "API-call quota exceeded; wait for the reset or upgrade your plan.")
        if used_tokens + request.usage.input_tokens + request.usage.output_tokens > plan.token_limit:
            raise MeteringError(429, "AI-token quota exceeded; wait for the reset or upgrade your plan.")

        response = GenerateResponse(text=f"Simulated response: {request.prompt}", usage=request.usage, cost=cost)
        session.add(UsageEvent(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            **request.usage.model_dump(),
            cost=cost,
            currency=policy.currency,
            pricing_version=policy.version,
            response_body=response.model_dump(mode="json"),
            created_at=now,
        ))
        session.flush()
    info(__name__, "Usage committed tenant_id=%s", tenant_id)
    return response
