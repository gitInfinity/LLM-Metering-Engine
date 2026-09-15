import os
import unittest
from decimal import Decimal
from unittest.mock import patch


RATES = {
    "INPUT_RATE_PER_MILLION": "2", "CACHED_RATE_PER_MILLION": "0.5",
    "OUTPUT_RATE_PER_MILLION": "8", "API_CALL_RATE": "0.001",
    "BILLING_CURRENCY": "USD", "PRICING_VERSION": "test-only",
}


class PricingTests(unittest.TestCase):
    def test_round_half_up_at_storage_precision(self):
        from src.schemas.models import TokenUsage
        from src.services.pricing import PricingPolicy
        with patch.dict(os.environ, {**RATES, "INPUT_RATE_PER_MILLION": "0.0000005",
                                    "CACHED_RATE_PER_MILLION": "0", "API_CALL_RATE": "0"}):
            self.assertEqual(PricingPolicy().cost(TokenUsage(input_tokens=1, output_tokens=0)),
                             Decimal("0.000000000001"))

    def test_cached_and_reasoning_are_not_double_counted(self):
        from src.schemas.models import TokenUsage
        from src.services.pricing import PricingPolicy
        with patch.dict(os.environ, RATES):
            cost = PricingPolicy().cost(TokenUsage(input_tokens=100, cached_input_tokens=20,
                                                  output_tokens=50, reasoning_tokens=10))
        self.assertEqual(cost, Decimal("0.001570"))


@unittest.skipUnless(os.getenv("RUN_DB_TESTS") == "1", "Requires configured PostgreSQL")
class APITests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from test_metering import MeteringTests
        from src.api.app import app
        from src.auth.service import AuthService
        self.fixture = MeteringTests()
        self.fixture.setUp()
        self.key_id, self.token = AuthService.issue_key(self.fixture.tenant_id)
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {self.token}", "Idempotency-Key": "api-test"}
        self.body = {"prompt": "hello", "usage": {"input_tokens": 60, "output_tokens": 40}}
        self.rates = patch.dict(os.environ, RATES)
        self.rates.start()

    def tearDown(self):
        from sqlalchemy import delete
        from src.db.db_models import APIKey
        with self.fixture.sessions.begin() as session:
            session.execute(delete(APIKey).where(APIKey.tenant_id == self.fixture.tenant_id))
        self.fixture.tearDown()
        self.client.close()
        self.rates.stop()

    def test_authentication_and_revocation(self):
        from src.auth.service import AuthService
        from src.db.db_models import APIKey
        for headers in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer invalid"}):
            response = self.client.get("/usage", headers=headers)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["www-authenticate"], "Bearer")
        with self.fixture.sessions() as session:
            self.assertNotEqual(session.get(APIKey, self.key_id).key_hash, self.token)
        AuthService.revoke_key(self.key_id)
        self.assertEqual(self.client.get("/usage", headers=self.headers).status_code, 401)

    def test_demo_cost_rollup_and_historical_pricing(self):
        from dotenv import dotenv_values
        from sqlalchemy import select
        from src.db.db_models import Plan, UsageEvent
        keys = tuple(RATES)
        config = {key: dotenv_values(".env.example")[key] for key in keys}
        self.assertEqual(config["PRICING_VERSION"], "demo-v1")
        with self.fixture.sessions.begin() as session:
            plan = session.get(Plan, self.fixture.plan_id)
            plan.api_call_limit, plan.token_limit = 10, 1000
        body = {"prompt": "cost evidence", "usage": {"input_tokens": 100, "cached_input_tokens": 20,
                                                     "output_tokens": 50, "reasoning_tokens": 10}}
        with patch.dict(os.environ, config):
            first = self.client.post("/generate", headers=self.headers, json=body)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(Decimal(first.json()["cost"]), Decimal("0.001570000000"))
            second = self.client.post("/generate", headers={**self.headers, "Idempotency-Key": "second"},
                                      json={"prompt": "second", "usage": {"input_tokens": 100, "cached_input_tokens": 50,
                                                                         "output_tokens": 20, "reasoning_tokens": 10}})
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(Decimal(second.json()["cost"]), Decimal("0.001285000000"))
            with patch.dict(os.environ, {"INPUT_RATE_PER_MILLION": "3", "PRICING_VERSION": "changed"}):
                replay = self.client.post("/generate", headers=self.headers, json=body)
                self.assertEqual(replay.status_code, 200, replay.text)
                self.assertEqual(replay.json(), first.json())
            usage = self.client.get("/usage", headers=self.headers).json()
            self.assertEqual((usage["api_calls_used"], usage["tokens_used"]), (2, 270))
            self.assertEqual(Decimal(usage["costs_by_currency"]["USD"]), Decimal("0.002855000000"))
            with self.fixture.sessions() as session:
                events = session.scalars(select(UsageEvent).where(UsageEvent.tenant_id == self.fixture.tenant_id)).all()
                self.assertEqual(len(events), 2)
                self.assertEqual({event.pricing_version for event in events}, {"demo-v1"})

    def test_inactive_subscription_cannot_generate_but_can_read_usage(self):
        from sqlalchemy import select
        from src.db.db_models import Subscription
        with self.fixture.sessions.begin() as session:
            subscription = session.scalar(select(Subscription).where(Subscription.tenant_id == self.fixture.tenant_id))
            subscription.status = "past_due"
        self.assertEqual(self.client.post("/generate", headers=self.headers, json=self.body).status_code, 402)
        result = self.client.get("/usage", headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["api_calls_used"], 0)

    def test_generation_replay_usage_and_quota(self):
        first = self.client.post("/generate", headers=self.headers, json=self.body)
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post("/generate", headers=self.headers, json=self.body)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(second.headers["cache-control"], "no-store")
        usage = self.client.get("/usage", headers=self.headers)
        self.assertEqual(usage.status_code, 200)
        self.assertEqual(usage.json()["api_calls_used"], 1)
        self.assertEqual(usage.json()["tokens_used"], 100)
        self.assertEqual(Decimal(usage.json()["costs_by_currency"]["USD"]), Decimal(first.json()["cost"]))
        conflict = self.client.post("/generate", headers=self.headers, json={**self.body, "prompt": "changed"})
        self.assertEqual(conflict.status_code, 409)
        denied = self.client.post("/generate", headers={**self.headers, "Idempotency-Key": "new"}, json=self.body)
        self.assertEqual(denied.status_code, 429)

    def test_generation_replay_survives_missing_pricing(self):
        from sqlalchemy import func, select
        from src.db.db_models import UsageEvent
        first = self.client.post("/generate", headers=self.headers, json=self.body)
        self.assertEqual(first.status_code, 200, first.text)
        with patch.dict(os.environ):
            for name in RATES:
                os.environ.pop(name, None)
            replay = self.client.post("/generate", headers=self.headers, json=self.body)
        with self.fixture.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(UsageEvent.id)).where(
                UsageEvent.tenant_id == self.fixture.tenant_id,
            )), 1)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), first.json())

    def test_validation_missing_pricing_and_expiry(self):
        from datetime import timedelta
        from sqlalchemy import func, select
        from src.db.db_models import APIKey
        missing = self.client.post("/generate", headers={"Authorization": self.headers["Authorization"]}, json=self.body)
        self.assertEqual(missing.status_code, 422)
        spoof = self.client.post("/generate", headers=self.headers, json={**self.body, "tenant_id": 1, "cost": 0})
        self.assertEqual(spoof.status_code, 422)
        with patch.dict(os.environ, {"INPUT_RATE_PER_MILLION": ""}):
            self.assertEqual(self.client.post("/generate", headers=self.headers, json=self.body).status_code, 503)
        with self.fixture.sessions.begin() as session:
            session.get(APIKey, self.key_id).expires_at = session.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
        self.assertEqual(self.client.get("/usage", headers=self.headers).status_code, 401)

    def test_tenant_isolation(self):
        from test_metering import MeteringTests
        from src.auth.service import AuthService
        from src.db.db_models import APIKey
        from sqlalchemy import delete
        other = MeteringTests()
        other.setUp()
        try:
            key_id, token = AuthService.issue_key(other.tenant_id)
            self.client.post("/generate", headers=self.headers, json=self.body)
            result = self.client.get("/usage", headers={"Authorization": f"Bearer {token}",
                                                       "X-Tenant-ID": str(self.fixture.tenant_id)})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["api_calls_used"], 0)
        finally:
            with other.sessions.begin() as session:
                session.execute(delete(APIKey).where(APIKey.tenant_id == other.tenant_id))
            other.tearDown()

    def test_checkout_customer_reuse_and_no_upgrade(self):
        from types import SimpleNamespace
        from stripe import Price
        from stripe.checkout import Session
        from sqlalchemy import select
        from src.db.db_models import Tenant, Subscription
        config = {"STRIPE_SECRET_KEY": "sk_test_fixture", "STRIPE_PRO_PRICE_ID": "price_fixture",
                  "STRIPE_CHECKOUT_SUCCESS_URL": "http://localhost:8000/docs",
                  "STRIPE_CHECKOUT_CANCEL_URL": "http://localhost:8000/docs"}
        with patch.dict(os.environ, config), patch("src.services.checkout.StripeClient") as factory:
            stripe = factory.return_value.v1
            stripe.prices.retrieve.return_value = Price.construct_from({
                "livemode": False, "active": True, "currency": "usd", "unit_amount": 2000,
                "billing_scheme": "per_unit",
                "recurring": {"interval": "month", "interval_count": 1, "usage_type": "licensed"},
            }, "sk_test_fixture")
            stripe.customers.create.return_value = SimpleNamespace(id="cus_checkout_test")
            stripe.subscriptions.list.return_value.auto_paging_iter.return_value = []
            stripe.checkout.sessions.list.return_value.auto_paging_iter.return_value = []
            saved = Session.construct_from({"url": "https://checkout.stripe.com/test_fixture",
                                           "metadata": {"tenant_id": str(self.fixture.tenant_id), "price_id": "price_fixture"}},
                                          "sk_test_fixture")
            stripe.checkout.sessions.create.return_value = saved
            self.assertEqual(self.client.post("/checkout").status_code, 401)
            self.assertEqual(self.client.post("/checkout", headers={"Authorization": self.headers["Authorization"]}).status_code, 422)
            first = self.client.post("/checkout", headers={**self.headers, "X-Tenant-ID": "-1"})
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json(), {"checkout_url": saved.url})
            params = stripe.checkout.sessions.create.call_args.args[0]
            self.assertEqual(params["customer"], "cus_checkout_test")
            self.assertEqual(params["client_reference_id"], str(self.fixture.tenant_id))
            self.assertEqual(params["subscription_data"]["metadata"]["tenant_id"], str(self.fixture.tenant_id))
            self.assertEqual(params["line_items"], [{"price": "price_fixture", "quantity": 1}])
            self.assertEqual(params["mode"], "subscription")
            stripe.checkout.sessions.list.return_value.auto_paging_iter.return_value = [saved]
            second = self.client.post("/checkout", headers=self.headers)
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(second.json(), first.json())
            stripe.customers.create.assert_called_once()
            stripe.checkout.sessions.create.assert_called_once()
            with self.fixture.sessions() as session:
                self.assertEqual(session.get(Tenant, self.fixture.tenant_id).stripe_customer_id, "cus_checkout_test")
                subscription = session.scalar(select(Subscription).where(Subscription.tenant_id == self.fixture.tenant_id))
                self.assertEqual(subscription.plan_id, self.fixture.plan_id)
                self.assertIsNone(subscription.stripe_subscription_id)
            stripe.subscriptions.list.return_value.auto_paging_iter.return_value = [SimpleNamespace(status="active")]
            self.assertEqual(self.client.post("/checkout", headers=self.headers).status_code, 409)

    def test_checkout_invalid_config_price_and_stripe_failure(self):
        from stripe import APIConnectionError, Price
        config = {"STRIPE_SECRET_KEY": "sk_test_fixture", "STRIPE_PRO_PRICE_ID": "price_fixture",
                  "STRIPE_CHECKOUT_SUCCESS_URL": "http://localhost:8000/docs",
                  "STRIPE_CHECKOUT_CANCEL_URL": "http://localhost:8000/docs"}
        with patch.dict(os.environ, config), patch("src.services.checkout.StripeClient") as factory:
            with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_live_fixture"}):
                self.assertEqual(self.client.post("/checkout", headers=self.headers).status_code, 503)
            factory.assert_not_called()
            factory.return_value.v1.prices.retrieve.return_value = Price.construct_from({"livemode": True}, "sk_test_fixture")
            self.assertEqual(self.client.post("/checkout", headers=self.headers).status_code, 503)
            factory.return_value.v1.customers.create.assert_not_called()
            factory.return_value.v1.prices.retrieve.side_effect = APIConnectionError("sensitive provider details")
            response = self.client.post("/checkout", headers=self.headers)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("sensitive", response.text)
