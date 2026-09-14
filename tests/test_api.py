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
