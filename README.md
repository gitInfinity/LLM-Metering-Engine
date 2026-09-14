# LLM Usage Metering & Billing Engine

A backend capstone project that tracks API calls and AI token usage per tenant, calculates per-request and 30-day costs, enforces quotas, and supports subscription upgrades through Stripe test mode.

**Status:** PostgreSQL setup, metering, bearer API-key authentication, generation/usage routes, and Stripe test Checkout are implemented. Signed webhook synchronization and the sandbox Pro upgrade are verified. Final usage-pricing decisions and submission evidence remain pending.

## Scope

- Users belong to tenants (customer organizations). Each tenant has its own subscription, quotas, and isolated usage records. Stripe's customer reference represents the tenant.
- One dummy billable endpoint simulates AI usage; no model call or AI API key is required.
- Each accepted request records usage exactly once. Retrying with the same idempotency key returns the original result without another charge.
- Requests are checked against quotas before being allowed. Blocked requests explain the reason: `429` for quota exhaustion or `402` when payment or an upgrade is required.
- Usage reporting shows 30-day usage, plan limits, and calculated costs.
- Stripe Checkout and verified webhooks manage Free-to-Pro upgrades and subscription status.

## Plans

| Plan | API calls / 30 days | AI tokens / 30 days |
| --- | ---: | ---: |
| Free | 1,000 | 100,000 |
| Pro | 10,000 | 1,000,000 |

Pricing rates will be pinned in configuration. Cached input tokens use a cheaper rate, and reasoning tokens count as output tokens. Cost calculations must avoid double-counting overlapping token categories. Exact totals will be verified in `EVIDENCE.md`.

Pro subscription pricing is $20 USD per calendar month in Stripe test mode. This flat subscription price is separate from the recorded token/API-call costs; the current scope does not bill additional usage charges. Quotas remain signup-anchored 30-day periods.

## Phase 3: Stripe test setup

In the Stripe Dashboard, select a sandbox/test environment and create a product named `Pro` with a recurring flat-rate price of **20.00 USD every month** (API amount: `2000` cents, currency: `usd`, interval: `month`). Reuse a matching product/price if one already exists. See [Stripe's product and price setup](https://docs.stripe.com/products-prices/manage-prices).

Add these entries to your existing local `.env`, preserving its database and generation-pricing settings:

```dotenv
STRIPE_SECRET_KEY=
STRIPE_PRO_PRICE_ID=
STRIPE_WEBHOOK_SECRET=
```

Set `STRIPE_SECRET_KEY` to the sandbox secret key and `STRIPE_PRO_PRICE_ID` to the recurring Price ID (`price_...`, not the Product ID). Keep both resources in the same sandbox. Store the secret only in the gitignored `.env`; see [Stripe API keys](https://docs.stripe.com/keys).

Leave `STRIPE_WEBHOOK_SECRET` blank until webhook setup. It is a separate signing secret from the endpoint configuration or local Stripe CLI listener, not the API secret key; see [Stripe webhook setup](https://docs.stripe.com/webhooks). The signed webhook handler synchronizes the local plan after delivery; a browser redirect alone never grants access. The current seed preserves existing plans and does not populate `plans.stripe_price_id` from this configuration.

Set the server-controlled return URLs in `.env` (the existing docs page is sufficient for local testing):

```dotenv
STRIPE_CHECKOUT_SUCCESS_URL=http://127.0.0.1:8000/docs
STRIPE_CHECKOUT_CANCEL_URL=http://127.0.0.1:8000/docs
```

Call `POST /checkout` with your bearer key and an `Idempotency-Key` header; no request body is needed. The JSON response contains `checkout_url`; open it in a browser. The service verifies the configured price is active, test-only, flat-rate 20 USD every month. It creates/reuses the tenant's Stripe customer under the tenant lock, attaches tenant metadata to Checkout and the future Stripe subscription, and reuses an open matching Checkout session. Reuse the same idempotency key for a retry; use a new key after an expired session. Stripe idempotency retention is finite, so this is not permanent local request deduplication.

An existing non-canceled/non-expired Stripe subscription returns 409. Missing/invalid configuration or Stripe failures return 503 without provider details. Checkout does not change quota periods or grant Pro access. Stripe calls have a 10-second timeout and one network retry; they hold the tenant lock, so slow Stripe responses can temporarily delay that tenant's metering. Tests mock Stripe while using PostgreSQL fixtures; sandbox Checkout and subscription synchronization were separately verified on 2026-09-14.

## Architecture

```text
Client -> Billable endpoint -> Tenant + idempotency check
                           -> Quota check -> Reject with 429 / 402
                           -> Record usage once + calculate cost

Client -> Usage endpoint -> Tenant's 30-day usage, limits, and cost

Client -> Stripe Checkout (test mode)
Stripe -> Signed webhook -> Verify + deduplicate -> Sync subscription
```

The database will contain tenants, plans, subscriptions, and usage events. Stripe is the source of truth for payment state; verified webhook events update the local subscription records.

## Build phases

| Phase / commit | Work | Completion gate |
| --- | --- | --- |
| 1. Design | Define schema, plans, API contract, and idempotency strategy. | Design captured in [DESIGN.md](DESIGN.md); completion requires committing it. |
| 2. Core billing logic | Implement usage metering, duplicate prevention, and quota enforcement. | Sending the same request twice creates one event; quota boundaries return the appropriate `429` / `402`. |
| 3. Stripe integration | Add test Checkout, signature verification, webhook deduplication, and subscription sync. | Test Checkout upgrades a tenant from Free to Pro through a verified webhook. |
| 4. Cost & finalization | Add cost rollups, verify token pricing, and finish documentation and evidence. | Usage totals match pinned pricing; every requirement has proof. |

## Current setup

Requires Python 3.12+, uv, and Docker Desktop running Linux containers. From the repository root, create your local configuration once:

```powershell
Copy-Item .env.example .env
uv sync
. .\.venv\Scripts\Activate.ps1
docker compose up -d --wait db
uv run --env-file .env -m src.db.database
uv run --env-file .env -m src.db.seed
```

The health-check command runs `SELECT 1` and prints `PostgreSQL connection successful.` on success. The app reads `DATABASE_URL`; Compose reads `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`. Keep these values consistent. The example credentials are for local development. If using an existing PostgreSQL server, set its connection URL and skip the Docker command.

SQLAlchemy uses Psycopg as the PostgreSQL driver. Use a `postgresql+psycopg://` URL; existing `postgresql://` URLs are also accepted. Load the environment before importing `src.db.database`. Its engine opens connections when needed, and `Base` is the base class for future ORM table models; `src/schemas/models.py` contains separate Pydantic API models.

Import sessions with `from src.db.database import SessionLocal` and table models with `from src.db.db_models import Tenant` from other application modules. Run module commands from the repository root. Use a fresh session for each unit of database work:

```python
from sqlalchemy import text
from src.db.database import SessionLocal

with SessionLocal.begin() as session:
    result = session.scalar(text("SELECT :value"), {"value": 1})
```

The context commits successful work, rolls back on exceptions, and closes the session, returning its connection to the engine's pool. Pass SQL values as query parameters rather than formatting them into SQL strings. Call `engine.dispose()` when the application shuts down.

Stop the database with `docker compose stop db`; its data remains in the named volume. PostgreSQL initialization credentials apply only when that volume is first initialized. Changing `.env` does not change an existing database's credentials.

Table definitions are in `src/db/db_models.py`; importing them registers SQLAlchemy metadata without creating tables. The seed command creates missing tables and inserts Free/Pro plans plus a Capstone Demo tenant, Demo User, and active Free subscription. Reruns preserve existing plans, users, signup timestamps, and subscriptions. Usage and Stripe event tables start empty. The demo name identifies the seed tenant; reserve it for demo data. Setup is transactional and serialized across simultaneous seed commands. `create_all` does not migrate or rename existing tables; schema migrations are not implemented yet.

## Database definitions

| Table | Responsibility |
| --- | --- |
| `tenants` | Organizations that own usage and a Stripe customer reference. |
| `users` | People belonging to a tenant; billing and quotas belong to the tenant. |
| `plans` | 30-day API-call and token quotas, with an optional Stripe price reference. |
| `subscriptions` | One current plan/status and period per tenant; Stripe references are optional for Free tenants. |
| `usage_events` | Accepted generations, token breakdown, exact decimal cost, currency, pricing version, and stored response for retries. |
| `api_keys` | Hashed tenant credentials with expiry and revocation timestamps. |
| `stripe_events` | Processed Stripe event IDs for webhook deduplication. |

Each usage event counts as one API call. Total tokens are input plus output; cached and reasoning counts are subsets. An idempotency key is unique within a tenant, and a request fingerprint supports detecting changed payloads on retries. Costs use `NUMERIC(20, 12)`; rates and currency must be configured; costs round half-up to 12 decimal places. Quota periods last exactly 30 days (720 hours), anchored to the tenant signup timestamp in UTC. The start is inclusive and the end is exclusive. January 31 resets on March 2 in a non-leap year and March 1 in a leap year. These quota periods are separate from Stripe billing dates.

These definitions enforce foreign keys, uniqueness, and valid token ranges. Tenant API-key authentication, concurrent quota enforcement, and retry handling are implemented. Webhook subscription updates and event deduplication commit atomically under the tenant lock.

## Project structure

```text
src/
  core/
    __init__.py   Shared infrastructure package
    logging.py    Application logging configuration
    errors.py     Shared exceptions and HTTP error handlers
  api/
    __init__.py   HTTP package
    app.py        FastAPI app and lifecycle
    routes.py     HTTP route registration and response contracts
    controllers.py Authenticated generate/usage request handlers
  auth/
    __init__.py   Authentication package
    service.py    Key issuance, authentication, expiry, and revocation
    dependencies.py Bearer authentication for routes
    cli.py        Local administrator key management
  schemas/
    __init__.py   API schema package
    models.py     API and token-usage validation models
  services/
    __init__.py   Business logic package
    metering.py   Atomic metering, retry handling, and quotas
    usage.py      Tenant usage aggregation
    pricing.py    Configurable server-side pricing
    checkout.py   Stripe test Checkout and tenant customer reuse
    webhooks.py   Signature verification and atomic subscription synchronization
  db/
    __init__.py   Database package
    periods.py    Signup-anchored 30-day quota windows
    seed.py       Create missing tables and insert repeatable demo data
    db_models.py  SQLAlchemy table definitions and relationships
    database.py   SQLAlchemy engine, sessions, ORM base, and health check
tests/
  test_errors.py Shared logging and HTTP error checks
  test_api.py     HTTP/authentication, pricing, and Checkout tests
  test_webhooks.py Signed events, duplicate delivery, subscription sync, and rollback
  test_metering.py PostgreSQL metering and concurrency integration tests
  test_seed.py    First quota period with database/application clock skew
  test_periods.py Date boundaries, leap years, and timezone checks
compose.yaml      Local PostgreSQL service and persistent volume
DESIGN.md         Phase 1 architecture and API contract
.env.example      Local database configuration template
pyproject.toml    Python dependencies
uv.lock           Locked dependency versions
```

## Submission deliverables

- `README.md`: overview, architecture, exact run and seed steps, and limitations.
- `capstone.yaml`: run, seed, optional test command, base URL, and endpoints to probe.
- `EVIDENCE.md`: test output or request transcripts proving each requirement.
- `BUILDLOG.md`: where AI helped, where it was wrong, and what was changed.
- `.env.example`: required environment variables with safe placeholders. Secrets must stay out of Git.

## Limitations

Core scope is two plans, two usage types, one simulated billable endpoint, and Stripe test payments. Real model calls, invoicing, proration, overage billing, usage alerts, and reconciliation are outside the core scope.

## Everything I learned

| Error ID | Mistake | Resolution and lesson |
| --- | --- | --- |
| QUOTA-001 | Seed initialization mixed database signup time with application time, allowing a before-signup error. | Use the stored signup timestamp for the first period's anchor and lookup. Clock-skew regression and live seeding passed. |
| DOMAIN-001 | Called people belonging to a tenant customers. | Renamed them users. The tenant is the customer organization and owns billing and quotas; verified ORM relationships and table definitions. |


## Quota period calculation

Call `subscription.set_quota_period(tenant.created_at, at)` on signup and before checking quota, within the application's transaction. The tenant signup timestamp stays fixed across resets and upgrades. The method updates the in-memory period fields; the caller must commit them. Quota enforcement calculates the current window on each billable request; no scheduler is required.

Run date checks with `uv run -m unittest discover -s tests`.

## Metering

Import `record_usage` from `src.services.metering` and `GenerateRequest` / `TokenUsage` from `src.schemas.models`. The function takes an authenticated tenant ID, request and idempotency key. It loads server pricing and calculates cost only after checking for a recorded response, so identical retries work even when current pricing is unavailable. New requests still require valid pricing configuration. No pricing rates are chosen yet; do not accept billing values from clients.

The service owns its transaction, locks the tenant, checks a canonical request fingerprint, and returns the saved response for identical retries. A changed payload with the same key raises `MeteringError(409)`. Missing tenants return 404, inactive/missing subscriptions return 402, and either exhausted quota returns 429. Active and trialing subscriptions may generate. Exact quota boundaries are allowed. Each successful simulated generation adds one event; cached/reasoning subsets are not counted twice.

Period lookup and event timestamps use the database clock after acquiring the lock. All future usage writers and subscription updates must take the same tenant lock. The service uses PostgreSQL's default READ COMMITTED isolation. HTTP routes authenticate the tenant and translate these exceptions into HTTP responses.

Run PostgreSQL integration tests against the configured local database after seeding. Tests create uniquely named test tenants/plans and remove only their own records:

```powershell
$env:RUN_DB_TESTS = "1"
uv run --env-file .env -m unittest discover -s tests -p test_metering.py
```
## Run the HTTP API

```powershell
uv run --env-file .env -m src.db.seed
uv run --env-file .env -m src.auth.cli issue --tenant-id <tenant-id> --days 90
uv run --env-file .env uvicorn src.api.app:app --host 127.0.0.1 --port 8000
```

Use the tenant ID from the `tenants` table. The local administrator CLI prints a newly generated key once; store it securely. Only its SHA-256 hash is stored. Keys expire after the requested lifetime (default 90 days, maximum 365). Revoke a key with `uv run --env-file .env -m src.auth.cli revoke --key-id <key-id>`. Issuance and revocation require local database access; there is no public key-issuance endpoint or password login. Use HTTPS when exposing the API beyond local development. Revocation blocks subsequent authentication; it does not cancel an already authorized request.

Swagger documentation: `http://127.0.0.1:8000/docs`. Enter the raw API key in Authorize.

| Route | Headers | Behavior |
| --- | --- | --- |
| `POST /generate` | `Authorization: Bearer <key>`, `Idempotency-Key: <unique-request-key>`, `Content-Type: application/json` | Validates simulated tokens, applies server pricing, and records usage once. |
| `GET /usage` | `Authorization: Bearer <key>` | Current period, plan/status, used/limit counts, and costs grouped by currency. |

Example generation JSON (send the body directly, without an HTTP-envelope wrapper):

```json
{"prompt":"Explain gravity","usage":{"input_tokens":100,"cached_input_tokens":20,"output_tokens":50,"reasoning_tokens":10}}
```

Responses use JSON, `Cache-Control: no-store`, and `X-Content-Type-Options: nosniff`. Invalid/missing/expired/revoked keys return 401 with `WWW-Authenticate: Bearer`. Invalid bodies or missing idempotency headers return 422; inactive subscriptions return 402; conflicts return 409; quotas return 429. Unavailable database or missing pricing configuration returns 503. Errors contain `error_code` and `message`. Client-supplied tenant IDs and costs are rejected in the generation body; tenant identity comes exclusively from the key.

Configure `INPUT_RATE_PER_MILLION`, `CACHED_RATE_PER_MILLION`, `OUTPUT_RATE_PER_MILLION`, `API_CALL_RATE`, `BILLING_CURRENCY`, and `PRICING_VERSION` in `.env` before generation. Blank placeholders intentionally do not define charges. These are rates you must choose, not provider prices fetched automatically. Cost = per-call rate + (uncached input × input rate + cached input × cached rate + all output × output rate) / 1,000,000. Reasoning tokens are already included in output. Costs are rounded half-up to 12 decimal places. Update the pricing version when rates change. Usage reporting works without configured rates and never adds amounts of different currencies together.

Run all tests against the initialized local database with `RUN_DB_TESTS=1` and `uv run --env-file .env -m unittest discover -s tests`. Integration tests use temporary test tenants and keys, never print raw test keys, and clean up their own records. Test pricing constants are synthetic and are not production defaults. Webhook tests use real signed payloads and Stripe SDK objects with mocked network calls; sandbox delivery was separately verified on 2026-09-14.
## Logging and errors

Import `debug`, `info`, `warning`, `error`, or `critical` from `src.core.logging` and call, for example, `info(__name__, "Usage committed tenant_id=%s", tenant_id)`. `exception` additionally includes the active exception traceback and must only be used when those details are safe. Use `configure_logging("DEBUG")` to enable debug output; the default is INFO. API startup and CLI entry points call `configure_logging()` once; logs go to stderr with timestamp, level, and module name. Shared domain exceptions live in `src.core.errors`; `src.core.errors` registers their HTTP handlers. Unexpected errors produce a generic 500 response, and database failures produce 503. Logs omit API keys, credentials, prompts, request bodies, and raw database exception details. Key issuance still prints its one-time secret to command output, never to the logger. Standard validation exceptions remain in schemas and date calculations.

## HTTP controller structure

`src/api/routes.py` maps HTTP methods and paths to handlers in `src/api/controllers.py`. Controllers receive validated schemas and authenticated tenant context, then call pricing, metering, or usage services. Shared error handlers translate exceptions into HTTP responses. Both routes retain bearer authentication; generation also requires `Idempotency-Key`. Their request and response contracts are available at `/docs` and `/openapi.json`. This implements the HTTP layer; Phase 1's committed design-document gate is separate.

## Local Stripe webhook testing

Install the [Stripe CLI](https://docs.stripe.com/stripe-cli) and authenticate to the same sandbox as the configured key and price. Start a listener:

```powershell
stripe login
stripe listen --events checkout.session.completed,customer.subscription.created,customer.subscription.updated,customer.subscription.deleted --forward-to http://127.0.0.1:8000/stripe/webhook
```

Copy the listener's `whsec_...` signing secret into `STRIPE_WEBHOOK_SECRET` in `.env`, then restart the API. Keep the listener running while completing the actual sandbox Checkout. Check for HTTP 200 deliveries and use authenticated `GET /usage` to verify Pro and its status. CLI-forwarded events require the CLI secret, not a Dashboard endpoint secret.

`POST /stripe/webhook` authenticates via `Stripe-Signature`, not tenant bearer credentials. Invalid/missing/expired signatures and live-mode events return 400. Unsupported event types are acknowledged without changing data. Supported events resolve the tenant exclusively by its stored Stripe customer ID; metadata cannot redirect an event to another tenant. Unknown customers, unavailable Stripe state, or missing local setup return 503 for retry.

Within the tenant lock, the handler checks the event ID and fetches current customer subscriptions from Stripe rather than trusting an old event snapshot. It matches the configured Pro price, quantity one, test mode, and tenant metadata. It prefers a nonterminal subscription, then the newest creation time. This prevents a delayed cancellation for an older subscription from overwriting a newer subscription. The status and Stripe subscription ID are stored with the Pro plan and event ID in one transaction. Stripe/network failures roll back the event record so delivery can retry. Stripe calls hold the tenant lock and can briefly delay metering.

Only active/trialing status permits generation. Past-due, unpaid, paused, canceled, incomplete, and expired subscriptions remain blocked with 402; cancellation does not automatically restore Free. Quota periods, signup time, and usage history are preserved. The configured Price ID is the mapping to the seeded Pro plan; the optional `plans.stripe_price_id` is not populated by this handler. No schema migration or volume reset is needed.

### Phase 3 verification

On 2026-09-14, sandbox Checkout completed for Pro at $20 USD/month. The initial subscription delivery was not confirmed while the CLI listener had connection errors. After restoring delivery, a metadata-only update to the existing Stripe subscription generated a signed `customer.subscription.updated` event. The handler recorded the event and synchronized the tenant to active Pro with 10,000 calls and 1,000,000 tokens, preserving the original quota period. The user confirmed the result through `GET /usage`; no second payment was created. All 30 tests passed with PostgreSQL enabled, including signature rejection, concurrent duplicates, delayed events, and rollback/retry checks.
