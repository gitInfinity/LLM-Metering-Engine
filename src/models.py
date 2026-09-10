from decimal import Decimal
from typing import Self

from pydantic import BaseModel, Field, model_validator


class TokenUsage(BaseModel):
    """Input includes cached tokens; output includes reasoning tokens."""

    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)
    cached_input_tokens: int = Field(default=0, ge=0, strict=True)
    reasoning_tokens: int = Field(default=0, ge=0, strict=True)

    @model_validator(mode="after")
    def validate_token_breakdown(self) -> Self:
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached_input_tokens cannot exceed input_tokens")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning_tokens cannot exceed output_tokens")
        return self


class GenerateRequest(BaseModel):
    """Prompt and simulated usage for the dummy generation endpoint."""

    prompt: str = Field(min_length=1)
    usage: TokenUsage


class GenerateResponse(BaseModel):
    """Generated text, measured usage, and server-calculated monetary cost."""

    text: str
    usage: TokenUsage
    cost: Decimal = Field(ge=0, allow_inf_nan=False)
    

class APIRequest(BaseModel):
    """
    Represents a request to the API.

    Attributes:
        endpoint (str): The API endpoint being accessed.
        method (str): The HTTP method used for the request (e.g., GET, POST).
        headers (dict): A dictionary of HTTP headers included in the request.
        body (GenerateRequest | None): Validated generation data, if applicable.
    """
    endpoint: str
    method: str
    headers: dict
    body: GenerateRequest | None = None
    

class APIResponse(BaseModel):
    """
    Represents a response from the API.

    Attributes:
        status_code (int): The HTTP status code of the response.
        headers (dict): A dictionary of HTTP headers included in the response.
        body (GenerateResponse | None): Validated generation result, if applicable.
    """
    status_code: int
    headers: dict
    body: GenerateResponse | None = None
    

class APIError(BaseModel):
    """
    Represents an error response from the API.

    Attributes:
        error_code (int): The specific error code returned by the API.
        message (str): A descriptive message explaining the error.
        details (dict | None): Additional details about the error, if available.
    """
    error_code: int
    message: str
    details: dict | None = None

    
