from typing import Annotated

from fastapi import Depends, Header

from src.auth.dependencies import require_tenant
from src.auth.service import AuthenticatedTenant
from src.schemas.models import GenerateRequest, GenerateResponse, UsageResponse
from src.services.metering import record_usage
from src.services.usage import get_usage


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
