from sqlalchemy import func, select

from src.db.database import SessionLocal
from src.db.db_models import Plan, Subscription, Tenant, UsageEvent
from src.db.periods import quota_period
from src.schemas.models import UsageResponse
from src.core.errors import MeteringError


def get_usage(tenant_id: int) -> UsageResponse:
    with SessionLocal.begin() as session:
        tenant = session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
        if tenant is None:
            raise MeteringError(404, "Tenant not found.")
        subscription = session.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
        if subscription is None:
            raise MeteringError(402, "A subscription is required.")
        plan = session.get(Plan, subscription.plan_id)
        start, end = quota_period(tenant.created_at, session.scalar(select(func.clock_timestamp())))
        rows = session.execute(select(
            UsageEvent.currency, func.count(UsageEvent.id),
            func.sum(UsageEvent.input_tokens + UsageEvent.output_tokens), func.sum(UsageEvent.cost),
        ).where(UsageEvent.tenant_id == tenant_id, UsageEvent.created_at >= start,
                UsageEvent.created_at < end).group_by(UsageEvent.currency)).all()
        return UsageResponse(
            period_start=start, period_end=end, plan=plan.name, subscription_status=subscription.status,
            api_calls_used=sum(row[1] for row in rows), api_call_limit=plan.api_call_limit,
            tokens_used=sum(row[2] for row in rows), token_limit=plan.token_limit,
            costs_by_currency={row[0]: row[3] for row in rows},
        )
