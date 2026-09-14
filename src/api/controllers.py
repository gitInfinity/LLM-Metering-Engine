from typing import Annotated

from fastapi import Depends, Header, Request
from starlette.concurrency import run_in_threadpool

from src.auth.dependencies import require_tenant
from src.auth.service import AuthenticatedTenant
from src.schemas.models import GenerateRequest, GenerateResponse, UsageResponse
from src.services.metering import record_usage
from src.services.usage import get_usage
from src.services.checkout import create_checkout
from src.schemas.models import CheckoutResponse
from src.services.webhooks import process_webhook


TenantAuth = Annotated[AuthenticatedTenant, Depends(require_tenant)]


def generate(
    request: GenerateRequest,
    tenant: TenantAuth,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> GenerateResponse:
    """Pass authenticated generation input to metering."""
    return record_usage(tenant.tenant_id, request, idempotency_key)


def usage(tenant: TenantAuth) -> UsageResponse:
    """Read only the usage belonging to the authenticated tenant."""
    return get_usage(tenant.tenant_id)


def checkout(
    tenant: TenantAuth,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> CheckoutResponse:
    """Start Pro Checkout for the authenticated tenant."""
    return create_checkout(tenant.tenant_id, idempotency_key)


async def stripe_webhook(request: Request, stripe_signature: Annotated[str, Header()] = "") -> dict:
    """Preserve raw bytes for Stripe signature verification."""
    return await run_in_threadpool(process_webhook, await request.body(), stripe_signature)
