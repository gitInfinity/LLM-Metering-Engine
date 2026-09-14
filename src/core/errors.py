from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException


from src.core.logging import info, warning, error


class MeteringError(Exception):
    """Expected business rejection with its HTTP status code."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class AuthenticationError(Exception):
    """Missing, invalid, revoked, or expired tenant credentials."""


class PricingUnavailable(Exception):
    """Server pricing cannot produce a valid charge."""


class CheckoutUnavailable(Exception):
    """Stripe Checkout cannot currently be created."""




def error_response(status: int, message: str, *, headers=None, details=None) -> JSONResponse:
    content = {"error_code": status, "message": message}
    if details is not None:
        content["details"] = details
    return JSONResponse(status_code=status, content=content, headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", **(headers or {}),
    })


async def metering_error(request: Request, exc: MeteringError):
    info(__name__, "Metering rejected status=%s", exc.status_code)
    return error_response(exc.status_code, str(exc))


async def authentication_error(request: Request, exc: AuthenticationError):
    info(__name__, "Authentication rejected")
    return error_response(401, str(exc), headers={"WWW-Authenticate": "Bearer"})


async def http_error(request: Request, exc: HTTPException):
    return error_response(exc.status_code, str(exc.detail), headers=exc.headers)


async def validation_error(request: Request, exc: RequestValidationError):
    # Avoid submitted values and unknown field names, which can contain secrets.
    info(__name__, "Request validation rejected")
    return error_response(422, "Invalid request.", details={"error_count": len(exc.errors())})


async def pricing_error(request: Request, exc: PricingUnavailable):
    warning(__name__, "Server pricing unavailable")
    return error_response(503, str(exc))


async def database_error(request: Request, exc: OperationalError):
    error(__name__, "Database operation unavailable")
    return error_response(503, "Database temporarily unavailable.")


async def checkout_error(request: Request, exc: CheckoutUnavailable):
    warning(__name__, "Stripe Checkout unavailable")
    return error_response(503, str(exc))


async def unexpected_error(request: Request, exc: Exception):
    # Exception messages/tracebacks may contain SQL parameters or credentials.
    error(__name__, "Unhandled application error type=%s", type(exc).__name__)
    return error_response(500, "Internal server error.")


def register_error_handlers(app: FastAPI) -> None:
    for error, handler in (
        (MeteringError, metering_error), (AuthenticationError, authentication_error),
        (HTTPException, http_error), (RequestValidationError, validation_error),
        (PricingUnavailable, pricing_error), (OperationalError, database_error),
        (CheckoutUnavailable, checkout_error),
        (Exception, unexpected_error),
    ):
        app.add_exception_handler(error, handler)
