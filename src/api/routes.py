from fastapi import APIRouter

from src.schemas.models import APIError, GenerateResponse, UsageResponse
from .controllers import generate, usage


router = APIRouter(responses={
    401: {"model": APIError, "description": "Missing, invalid, expired, or revoked bearer API key."},
    402: {"model": APIError, "description": "Subscription or payment required."},
    404: {"model": APIError, "description": "Tenant not found."},
    422: {"model": APIError, "description": "Invalid request body or headers."},
    503: {"model": APIError, "description": "Database or server pricing unavailable."},
})

router.add_api_route(
    "/generate", generate, methods=["POST"], response_model=GenerateResponse,
    tags=["Generation"], summary="Generate a simulated response and meter usage",
    responses={
        409: {"model": APIError, "description": "Idempotency key reused for a different request."},
        429: {"model": APIError, "description": "API-call or token quota exceeded."},
    },
)
router.add_api_route(
    "/usage", usage, methods=["GET"], response_model=UsageResponse,
    tags=["Usage"], summary="Read the authenticated tenant's current quota period",
)
