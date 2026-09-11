import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select

from src.db.database import SessionLocal
from src.db.db_models import APIKey, Tenant
from src.core.errors import AuthenticationError
from src.core.logging import info




@dataclass(frozen=True)
class AuthenticatedTenant:
    tenant_id: int
    key_id: int


class AuthService:
    @staticmethod
    def issue_key(tenant_id: int, valid_days: int = 90) -> tuple[int, str]:
        if not 1 <= valid_days <= 365:
            raise ValueError("Key lifetime must be between 1 and 365 days.")
        token = secrets.token_urlsafe(32)
        with SessionLocal.begin() as session:
            if session.get(Tenant, tenant_id) is None:
                raise ValueError("Tenant not found.")
            now = session.scalar(select(func.clock_timestamp()))
            key = APIKey(tenant_id=tenant_id, key_hash=hashlib.sha256(token.encode()).hexdigest(),
                         expires_at=now + timedelta(days=valid_days))
            session.add(key)
            session.flush()
            key_id = key.id
        info(__name__, "API key issued tenant_id=%s key_id=%s", tenant_id, key_id)
        return key_id, token

    @staticmethod
    def authenticate(token: str) -> AuthenticatedTenant:
        if len(token) != 43 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in token):
            raise AuthenticationError("Invalid or expired API key.")
        digest = hashlib.sha256(token.encode()).hexdigest()
        with SessionLocal() as session:
            key = session.scalar(select(APIKey).where(
                APIKey.key_hash == digest, APIKey.revoked_at.is_(None),
                APIKey.expires_at > func.clock_timestamp(),
            ))
            if key is None:
                raise AuthenticationError("Invalid or expired API key.")
            return AuthenticatedTenant(tenant_id=key.tenant_id, key_id=key.id)

    @staticmethod
    def revoke_key(key_id: int) -> None:
        with SessionLocal.begin() as session:
            key = session.get(APIKey, key_id)
            if key is None:
                raise ValueError("API key not found.")
            key.revoked_at = session.scalar(select(func.clock_timestamp()))
        info(__name__, "API key revoked key_id=%s", key_id)
