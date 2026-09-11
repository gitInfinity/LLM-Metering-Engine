import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

from src.schemas.models import TokenUsage
from src.core.errors import PricingUnavailable


class PricingPolicy:
    """Server-configured rates per million tokens, plus a per-call charge."""

    def __init__(self):
        try:
            self.input_rate = Decimal(os.environ["INPUT_RATE_PER_MILLION"])
            self.cached_rate = Decimal(os.environ["CACHED_RATE_PER_MILLION"])
            self.output_rate = Decimal(os.environ["OUTPUT_RATE_PER_MILLION"])
            self.call_rate = Decimal(os.environ["API_CALL_RATE"])
            self.currency = os.environ["BILLING_CURRENCY"]
            self.version = os.environ["PRICING_VERSION"]
            rates = (self.input_rate, self.cached_rate, self.output_rate, self.call_rate)
            if any(not rate.is_finite() or rate < 0 or rate >= 100000000 for rate in rates):
                raise ValueError
            if self.cached_rate > self.input_rate:
                raise ValueError
            if len(self.currency) != 3 or not self.currency.isascii() or not self.currency.isalpha() or not self.currency.isupper():
                raise ValueError
            if not self.version.strip() or len(self.version) > 100:
                raise ValueError
        except (KeyError, InvalidOperation, ValueError):
            raise PricingUnavailable("Server pricing is missing or invalid.") from None

    def cost(self, usage: TokenUsage) -> Decimal:
        with localcontext() as context:
            context.prec = 50
            cost = self.call_rate + (
                (usage.input_tokens - usage.cached_input_tokens) * self.input_rate
                + usage.cached_input_tokens * self.cached_rate
                + usage.output_tokens * self.output_rate
            ) / Decimal(1000000)
            cost = cost.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_UP)
            if cost >= 100000000:
                raise PricingUnavailable("Calculated cost exceeds supported storage precision.")
            return cost
