from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Tenant(Base):
    """Organization that owns customers, a subscription, and usage."""

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    customers: Mapped[list[Customer]] = relationship(back_populates="tenant")
    subscription: Mapped[Subscription | None] = relationship(back_populates="tenant")
    usage_events: Mapped[list[UsageEvent]] = relationship(back_populates="tenant")


class Customer(Base):
    """A customer belonging to one tenant; distinct from a Stripe customer."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))

    tenant: Mapped[Tenant] = relationship(back_populates="customers")


class Plan(Base):
    """Monthly quota definitions; Free and Pro values are seeded separately."""

    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("api_call_limit >= 0", name="ck_plans_api_call_limit"),
        CheckConstraint("token_limit >= 0", name="ck_plans_token_limit"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    api_call_limit: Mapped[int] = mapped_column(BigInteger)
    token_limit: Mapped[int] = mapped_column(BigInteger)
    stripe_price_id: Mapped[str | None] = mapped_column(String(255), unique=True)

    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="plan")


class Subscription(Base):
    """One current subscription per tenant, including the local Free plan."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("period_end > period_start", name="ck_subscriptions_period"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), unique=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    status: Mapped[str] = mapped_column(String(50))
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="subscription")
    plan: Mapped[Plan] = relationship(back_populates="subscriptions")


class UsageEvent(Base):
    """One accepted generation: one API call plus its token usage and result.

    Input includes cached tokens; output includes reasoning tokens. Total usage
    is input_tokens + output_tokens. Rejected requests have no billable event.
    """

    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_usage_tenant_key"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="ck_usage_tokens"),
        CheckConstraint("cached_input_tokens >= 0 AND cached_input_tokens <= input_tokens", name="ck_usage_cached_tokens"),
        CheckConstraint("reasoning_tokens >= 0 AND reasoning_tokens <= output_tokens", name="ck_usage_reasoning_tokens"),
        CheckConstraint("cost >= 0 AND cost != 'NaN'::numeric", name="ck_usage_cost"),
        Index("ix_usage_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    idempotency_key: Mapped[str] = mapped_column(Text)
    request_fingerprint: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(BigInteger)
    output_tokens: Mapped[int] = mapped_column(BigInteger)
    cached_input_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    reasoning_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    cost: Mapped[Decimal] = mapped_column(Numeric(20, 12))
    currency: Mapped[str] = mapped_column(String(3))
    pricing_version: Mapped[str] = mapped_column(String(100))
    response_body: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped[Tenant] = relationship(back_populates="usage_events")


class StripeEvent(Base):
    """Deduplication record written atomically with a verified event's updates."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(255))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
