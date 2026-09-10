# LLM Usage Metering & Billing Engine

A backend capstone project that tracks API calls and AI token usage per tenant, calculates per-request and monthly costs, enforces quotas, and supports subscription upgrades through Stripe test mode.

**Status:** API models, SQLAlchemy table definitions, and PostgreSQL connection boilerplate are in place. Billing features below are planned and will be built in four phases, each ending with a commit.

## Scope

- Customers belong to tenants. Each tenant has its own subscription, quotas, and isolated usage records.
- One dummy billable endpoint simulates AI usage; no model call or AI API key is required.
- Each accepted request records usage exactly once. Retrying with the same idempotency key returns the original result without another charge.
- Requests are checked against quotas before being allowed. Blocked requests explain the reason: `429` for quota exhaustion or `402` when payment or an upgrade is required.
- Usage reporting shows monthly usage, plan limits, and calculated costs.
- Stripe Checkout and verified webhooks manage Free-to-Pro upgrades and subscription status.

## Plans

| Plan | API calls / month | AI tokens / month |
| --- | ---: | ---: |
| Free | 1,000 | 100,000 |
| Pro | 10,000 | 1,000,000 |

Pricing rates will be pinned in configuration. Cached input tokens use a cheaper rate, and reasoning tokens count as output tokens. Cost calculations must avoid double-counting overlapping token categories. Exact totals will be verified in `EVIDENCE.md`.

## Architecture

```text
Client -> Billable endpoint -> Tenant + idempotency check
                           -> Quota check -> Reject with 429 / 402
                           -> Record usage once + calculate cost

Client -> Usage endpoint -> Tenant's monthly usage, limits, and cost

Client -> Stripe Checkout (test mode)
Stripe -> Signed webhook -> Verify + deduplicate -> Sync subscription
```

The database will contain tenants, plans, subscriptions, and usage events. Stripe is the source of truth for payment state; verified webhook events update the local subscription records.

## Build phases

| Phase / commit | Work | Completion gate |
| --- | --- | --- |
| 1. Design | Define schema, plans, API contract, and idempotency strategy. | Commit a one-page design document. |
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
```

The final command runs `SELECT 1` and prints `PostgreSQL connection successful.` on success. The app reads `DATABASE_URL`; Compose reads `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`. Keep these values consistent. The example credentials are for local development. If using an existing PostgreSQL server, set its connection URL and skip the Docker command.

SQLAlchemy uses Psycopg as the PostgreSQL driver. Use a `postgresql+psycopg://` URL; existing `postgresql://` URLs are also accepted. Load the environment before importing `src.db.database`. Its engine opens connections when needed, and `Base` is the base class for future ORM table models; `src/models.py` contains separate Pydantic API models.

Import sessions with `from src.db.database import SessionLocal` and table models with `from src.db.db_models import Tenant` from other application modules. Run module commands from the repository root. Use a fresh session for each unit of database work:

```python
from sqlalchemy import text
from src.db.database import SessionLocal

with SessionLocal.begin() as session:
    result = session.scalar(text("SELECT :value"), {"value": 1})
```

The context commits successful work, rolls back on exceptions, and closes the session, returning its connection to the engine's pool. Pass SQL values as query parameters rather than formatting them into SQL strings. Call `engine.dispose()` when the application shuts down.

Stop the database with `docker compose stop db`; its data remains in the named volume. PostgreSQL initialization credentials apply only when that volume is first initialized. Changing `.env` does not change an existing database's credentials.

Table definitions are in `src/db/db_models.py`; importing them registers SQLAlchemy metadata without creating tables. Migrations, physical table creation, demo seed data, API routes, and Stripe integration are not implemented yet.

## Database definitions

| Table | Responsibility |
| --- | --- |
| `tenants` | Organizations that own usage and a Stripe customer reference. |
| `customers` | Individual customers linked to their tenant. |
| `plans` | Monthly API-call and token quotas, with an optional Stripe price reference. |
| `subscriptions` | One current plan/status and period per tenant; Stripe references are optional for Free tenants. |
| `usage_events` | Accepted generations, token breakdown, exact decimal cost, currency, pricing version, and stored response for retries. |
| `stripe_events` | Processed Stripe event IDs for webhook deduplication. |

Each usage event counts as one API call. Total tokens are input plus output; cached and reasoning counts are subsets. An idempotency key is unique within a tenant, and a request fingerprint supports detecting changed payloads on retries. Costs use `NUMERIC(20, 12)`; rates, currency choice, and rounding policy remain to be defined. Monthly queries use the tenant's period with an inclusive start and exclusive end; the calendar-versus-subscription reset policy remains to be defined.

These definitions enforce foreign keys, uniqueness, and valid token ranges. Tenant authorization, concurrent quota enforcement, retry handling, and atomic webhook processing must still be implemented in the application.

## Project structure

```text
src/
  models.py       API and token-usage validation models
  db/
    __init__.py   Database package
    db_models.py  SQLAlchemy table definitions and relationships
    database.py   SQLAlchemy engine, sessions, ORM base, and health check
compose.yaml      Local PostgreSQL service and persistent volume
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
