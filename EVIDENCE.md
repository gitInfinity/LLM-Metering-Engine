# Capstone verification evidence

Verified on 2026-09-16 against the local PostgreSQL database unless a historical date is stated. No credentials, bearer keys, Checkout URLs, or card details are included. This covers the requirements recorded in README and DESIGN; the assignment specifies manifest fields but no nested endpoint example.

## Reproduce the automated checks

From the repository root, configure `.env`, start PostgreSQL, and seed Free/Pro plans:

```powershell
uv sync --locked
docker compose up -d --wait db
uv run --env-file .env -m src.db.database
uv run --env-file .env -m src.db.seed
$env:RUN_DB_TESTS = "1"
uv run --env-file .env -m unittest discover -s tests
```

For this run, uv used an alternate writable cache (`--cache-dir "$env:TEMP\capstone-uv-cache"`) and `--offline`; execution used the installed locked environment. Dependency sync reported 28 resolved packages and 27 audited packages. The health check printed `PostgreSQL connection successful.` and seeding printed `Tables ready; demo data seeded`.

Actual unittest summary:

```text
Ran 32 tests in 13.509s

OK
```

No tests were skipped in this database-enabled run. The Starlette TestClient/httpx deprecation warning remains; it did not fail the suite. Stripe API calls in automated tests are mocked; webhook signatures and Stripe SDK response objects are real test objects.

## Requirement coverage

| Requirement | Repeatable evidence |
| --- | --- |
| Tenant authentication and isolation | `test_authentication_and_revocation`, `test_validation_missing_pricing_and_expiry`, `test_tenant_isolation`, `test_same_key_is_independent_between_tenants` |
| Exactly-once generation retries and 409 conflicts | `test_generation_replay_usage_and_quota`, `test_replay_conflict_and_quota`, `test_concurrent_quota_and_duplicate` |
| Concurrent quota enforcement and 429 | `test_concurrent_different_keys`, `test_token_rejection_does_not_consume_call`, `test_generation_replay_usage_and_quota` |
| Inactive subscription returns 402 | `test_inactive_subscription_cannot_generate_but_can_read_usage`, `test_reset_payment_and_tenant_isolation`, webhook cancellation test |
| Signup-anchored 30-day periods | `tests/test_periods.py`, `tests/test_seed.py`, `test_reset_payment_and_tenant_isolation` |
| Exact costs and immutable historical pricing | `test_demo_cost_rollup_and_historical_pricing`, `test_generation_replay_survives_missing_pricing` |
| Cached/reasoning subsets and rounding | `test_cached_and_reasoning_are_not_double_counted`, `test_round_half_up_at_storage_precision` |
| Checkout customer reuse and no premature upgrade | `test_checkout_customer_reuse_and_no_upgrade` |
| Test-only Checkout and safe provider failures | `test_checkout_invalid_config_price_and_stripe_failure` |
| Signed webhooks and duplicate protection | `test_bad_signature_expiry_and_live_event`, `test_signed_upgrade_duplicate_and_period_preservation`, `test_concurrent_duplicate` |
| Delayed events, cancellation, and rollback | `test_delayed_event_uses_current_state_and_cancellation_blocks_usage`, `test_provider_failure_rolls_back_and_retry_succeeds`, `test_customer_binding_and_price_mismatch` |
| Shared error/logging behavior | `tests/test_errors.py` |

## Exact demo-v1 costs

Approved synthetic USD rates: uncached input 2/million, cached input 0.5/million, output 8/million, and 0.001/call. Reasoning is included in output; cached input is included in input. Costs are rounded half-up to 12 decimal places.

The HTTP/database regression `test_demo_cost_rollup_and_historical_pricing` verified:

| Request | Input | Cached subset | Output | Reasoning subset | Cost USD |
| --- | ---: | ---: | ---: | ---: | ---: |
| First | 100 | 20 | 50 | 10 | 0.001570000000 |
| Second | 100 | 50 | 20 | 10 | 0.001285000000 |
| First retried after rate/version change | Same | Same | Same | Same | Original response; no new charge |
| Period total | | | | | 0.002855000000 |

First: `0.001 + (80*2 + 20*0.5 + 50*8)/1000000`.
Second: `0.001 + (50*2 + 50*0.5 + 20*8)/1000000`.

Verified rollup: 2 calls, 270 total tokens, 2 stored events, both retaining `demo-v1`. These are assertions from the executed HTTP/database test, not a fabricated live curl transcript. The rounding test separately verifies that an exact half-unit at the twelfth decimal place rounds up using synthetic boundary rates.

## Application startup

A temporary Uvicorn process was launched on loopback port 8765 on 2026-09-16 and stopped after verification. `/docs` and `/openapi.json` returned 200, all four application routes were present, and unauthenticated `/usage` returned 401. Port 8000 remains the documented normal run port. This was a real socket check, separate from TestClient tests.

## Stripe sandbox evidence (2026-09-14)

The user completed the $20 USD/month Pro sandbox Checkout. Listener connection problems initially prevented confirmation of subscription delivery. After listener recovery, a metadata-only update to the existing subscription generated `customer.subscription.updated`; no additional payment was made. The local Stripe event record was observed and the usage service returned:

```json
{"period_start":"2026-09-11T15:16:11.357908Z","period_end":"2026-10-11T15:16:11.357908Z","plan":"Pro","subscription_status":"active","api_calls_used":0,"api_call_limit":10000,"tokens_used":0,"token_limit":1000000,"costs_by_currency":{}}
```

The user then independently confirmed Pro in `/usage`. This historical sandbox check establishes subscription synchronization; it does not claim that the original `checkout.session.completed` delivery was observed. Automated signed-event coverage includes that event type. Sandbox payment was not repeated on 2026-09-16.

## Verification limits

The local database and environment already existed; this is not a clean-machine installation or container-image build claim. There is no configured lint/typecheck gate or application Dockerfile. PostgreSQL is containerized by Compose; the API runs through uv. The manifest includes the supplied evaluator fields; the nested endpoint format and external evaluator execution are unverified. See README for operational limitations and setup.
