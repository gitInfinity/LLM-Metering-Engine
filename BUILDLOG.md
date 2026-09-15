# Build log

This is a factual summary of AI-assisted work and user decisions, based on this session and its prior handoff. It is not a verbatim transcript.

## Scope and decisions

The user selected a Python multi-tenant metering capstone with simulated generation, PostgreSQL persistence, Free/Pro quotas, Stripe sandbox subscriptions, and JSON API responses. The user explicitly chose signup-anchored periods of exactly 30 days rather than calendar months, MVC with services owning business logic and transactions, uv tooling, and minimal changes. Pro billing was set to $20 USD per calendar month independently of the quota period. Demo usage rates were approved as `demo-v1`, separately recorded rather than billed as additional Stripe charges.

## Work by phase

| Phase | AI contribution and validation | Commit/status |
| --- | --- | --- |
| 1: Design and foundation | Documented architecture, schemas, plans, idempotency, PostgreSQL setup, authentication, and API contracts. Implementation extended into core metering. | `00b44f3` |
| 2: Metering | Tenant locking, quota checks, atomic usage records, retries, authentication, cost/usage services. Fixed retries failing when pricing became unavailable; 22 database-enabled tests passed. | `e3fe1a1` |
| 3: Stripe | Authenticated Checkout, customer reuse, verified webhooks, current-state refresh, atomic event deduplication, and regression tests. 30 tests passed and sandbox upgrade verified with user participation. | `5469359` |
| 4: Finalization | Pinned demo rates, verified stored pricing and retries, added exact HTTP cost-rollup and rounding coverage, assembled manifest and evidence, and checked startup/setup. | Working changes; 32 tests passed on 2026-09-16 |

## Mistakes and corrections

| Mistake | What changed | Repeatable protection |
| --- | --- | --- |
| People were initially named customers, confusing them with the paying tenant. | Renamed the member entity to User; Stripe customer belongs to Tenant. | ORM/domain checks recorded as DOMAIN-001. |
| Seed initialization mixed application time with database signup time. | First quota window uses the stored signup time for both anchor and lookup. | Clock-skew regression, QUOTA-001. |
| Controller loaded pricing before idempotency lookup. | Pricing moved into metering after stored-response lookup. | Retry after pricing removal; RETRY-001. |
| Checkout used dictionary methods on Stripe SDK objects. Plain-dictionary mocks masked the error. | Convert SDK objects with `to_dict()` and use real SDK response objects in tests. | Checkout price/reuse regressions; CHECKOUT-001. |

The durable business-regression details are in `engineering-lessons.md`. AI-generated tests alone were insufficient to discover the Stripe response mismatch; actual sandbox use exposed it, and the mocks were corrected.

## User validation and remaining boundaries

The user configured the Stripe sandbox, completed test Checkout, and confirmed Pro after webhook delivery. The first listener session had connection errors; a metadata-only update generated a fresh subscription event after recovery. Database timeouts delayed some checks until PostgreSQL became available. These are setup observations, not additional business-error entries.

No real model calls, real payments, production deployment, schema migrations, automatic downgrade to Free, or overage charges were implemented. The user supplied the required top-level manifest fields; no nested endpoint example was provided. Credentials remain local and are excluded from these artifacts. Phase 4 has not been committed or pushed by this finalization task.
