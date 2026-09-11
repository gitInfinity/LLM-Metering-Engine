# Phase 1: Usage metering and billing design

## Architecture and ownership

Python/FastAPI controllers validate HTTP input and identify the tenant through bearer API-key authentication. Services own pricing, metering, usage aggregation, and transactions. SQLAlchemy with Psycopg stores data in PostgreSQL. Pydantic schemas define JSON requests and responses. Shared logging and error handling live in `src/core/`.

A tenant is the customer organization; users belong to it. Subscription, quotas, and charges belong to the tenant. Clients cannot select a different tenant through request bodies or headers.

## Data model

| Table | Purpose and constraints |
| --- | --- |
| `tenants`, `users` | Organizations and their members; each user references one tenant. |
| `plans` | Unique plan names and nonnegative API-call/token limits. |
| `subscriptions` | One current subscription per tenant; plan, status, Stripe reference, and quota-period boundaries. |
| `usage_events` | One accepted generation; token breakdown, decimal cost, currency, pricing version, request fingerprint, and saved response. Unique `(tenant_id, idempotency_key)`. |
| `api_keys` | Unique SHA-256 hashes of random tenant keys, expiry, and revocation timestamps. Raw keys are shown once by the administrator CLI. |
| `stripe_events` | Unique processed Stripe event IDs for future webhook deduplication. |

Free allows 1,000 API calls and 100,000 tokens per period; Pro allows 10,000 calls and 1,000,000 tokens. Periods last exactly 30 days (720 hours), anchored to signup in UTC, with inclusive start and exclusive end. This explicit project policy is separate from Stripe billing dates. Database time is used for metering to avoid application/database clock differences.

## HTTP contract

Both routes require `Authorization: Bearer <api-key>`. Generation additionally requires `Content-Type: application/json` and a nonempty `Idempotency-Key` of at most 255 characters.

- `POST /generate`: body is `{"prompt":"Explain gravity","usage":{"input_tokens":100,"cached_input_tokens":20,"output_tokens":50,"reasoning_tokens":10}}`. Returns 200 with simulated `text`, `usage`, and decimal `cost` serialized as a string.
- `GET /usage`: returns 200 with `period_start`, `period_end`, `plan`, `subscription_status`, used/limit counts for API calls and tokens, and `costs_by_currency`. Reading usage does not consume quota.

Errors contain `error_code` and `message`: 401 for invalid/missing/expired/revoked keys (with `WWW-Authenticate: Bearer`), 402 for subscription/payment requirements, 404 for a missing tenant, 409 for conflicting key reuse, 422 for invalid input, 429 for exceeded quotas, and 503 for unavailable database/pricing. Responses disable caching. OpenAPI details are exposed at `/docs` and `/openapi.json`.

## Metering and idempotency

In a PostgreSQL READ COMMITTED transaction, lock the tenant row, then check for a prior event. An identical normalized request returns its saved result; a different fingerprint with the same key returns 409. New requests require an active or trialing subscription. Calculate the current period, aggregate its tenant-scoped usage, and reject if adding one call or the requested tokens exceeds either limit. Exact limits are allowed. Insert the event and response in the same transaction. Rejections roll back; retries never add usage. All future usage writers and subscription updates must follow the same tenant-lock convention.

Input includes cached tokens; output includes reasoning tokens. Total quota tokens are input plus output. Server-configured pricing charges uncached input, cached input, and all output at their respective rates, plus a per-call rate. Costs round half-up to 12 decimal places and use `NUMERIC(20,12)`. Actual rates/currency must still be chosen; missing pricing returns 503. Clients cannot supply prices. The generation endpoint is simulated, so requested usage is known before acceptance.

## Later phases and validation

Stripe test Checkout and signed, deduplicated subscription webhooks are Phase 3 work. Final pinned pricing and complete evidence are Phase 4 work. No real model call, overage billing, proration, or invoicing is required. Current tests cover date boundaries, clock skew, retries, concurrency, quotas, authentication, tenant isolation, pricing arithmetic, and error handling. See README for setup and test commands.
