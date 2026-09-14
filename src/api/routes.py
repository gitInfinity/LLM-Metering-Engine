from fastapi import APIRouter

from src.schemas.models import APIError, GenerateResponse, UsageResponse
from .controllers import generate, usage
from .controllers import checkout, stripe_webhook
from src.schemas.models import CheckoutResponse


router = APIRouter(responses={
    401: {"model": APIError, "description": "Missing, invalid, expired, or revoked bearer API key."},
    402: {"model": APIError, "description": "Subscription or payment required."},
    404: {"model": APIError, "description": "Tenant not found."},
    422: {"model": APIError, "description": "Invalid request body or headers."},
    503: {"model": APIError, "description": "Database or server pricing unavailable."},
})

router.add_api_route(
    "/checkout", checkout, methods=["POST"], response_model=CheckoutResponse,
    tags=["Billing"], summary="Start Stripe test Checkout for Pro",
    responses={409: {"model": APIError, "description": "Existing Stripe subscription."},
               503: {"model": APIError, "description": "Stripe or Checkout configuration unavailable."}},
)

router.add_api_route(
    "/stripe/webhook", stripe_webhook, methods=["POST"], tags=["Billing"],
    summary="Receive signed Stripe test subscription events",
    responses={400: {"model": APIError, "description": "Invalid event or signature."}},
)

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
