from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .service import AuthenticatedTenant, AuthService
from src.core.errors import AuthenticationError


bearer = HTTPBearer(auto_error=False)


def require_tenant(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> AuthenticatedTenant:
    if credentials is None:
        raise AuthenticationError("Bearer API key required.")
    return AuthService.authenticate(credentials.credentials)
