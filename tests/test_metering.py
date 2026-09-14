import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from threading import Barrier
from uuid import uuid4


@unittest.skipUnless(os.getenv("RUN_DB_TESTS") == "1", "Set RUN_DB_TESTS=1 for PostgreSQL integration tests")
class MeteringTests(unittest.TestCase):
    def setUp(self):
        from test_api import RATES
        rates = patch.dict(os.environ, RATES)
        rates.start()
        self.addCleanup(rates.stop)
        from src.db.database import SessionLocal
        from src.db.db_models import Plan, Subscription, Tenant
        self.sessions = SessionLocal
        with self.sessions.begin() as session:
            plan = Plan(name=f"test-{uuid4().hex}", api_call_limit=1, token_limit=100)
            tenant = Tenant(name=f"test-{uuid4().hex}")
            session.add_all([plan, tenant])
            session.flush()
            sub = Subscription(tenant=tenant, plan=plan, status="active")
            sub.set_quota_period(tenant.created_at, tenant.created_at)
            session.add(sub)
            self.tenant_id, self.plan_id = tenant.id, plan.id

    def tearDown(self):
        from sqlalchemy import delete
        from src.db.db_models import Plan, Subscription, Tenant, UsageEvent
        with self.sessions.begin() as session:
            session.execute(delete(UsageEvent).where(UsageEvent.tenant_id == self.tenant_id))
            session.execute(delete(Subscription).where(Subscription.tenant_id == self.tenant_id))
            session.execute(delete(Tenant).where(Tenant.id == self.tenant_id))
            session.execute(delete(Plan).where(Plan.id == self.plan_id))
        self.doCleanups()

    def record(self, key, tokens=60, tenant_id=None):
        from src.schemas.models import GenerateRequest, TokenUsage
        from src.services.metering import record_usage
        return record_usage(
            self.tenant_id if tenant_id is None else tenant_id,
            GenerateRequest(prompt="test", usage=TokenUsage(
                input_tokens=tokens, output_tokens=40, cached_input_tokens=20, reasoning_tokens=10,
            )), key,
        )

    def test_replay_conflict_and_quota(self):
        from src.services.metering import MeteringError
        result = self.record("same")
        self.assertEqual(self.record("same"), result)
        for key, tokens, status in (("same", 59, 409), ("new", 60, 429)):
            with self.assertRaises(MeteringError) as error:
                self.record(key, tokens)
            self.assertEqual(error.exception.status_code, status)

    def test_token_rejection_does_not_consume_call(self):
        from src.services.metering import MeteringError
        with self.assertRaises(MeteringError) as error:
            self.record("too-many", 61)
        self.assertEqual(error.exception.status_code, 429)
        self.record("allowed")

    def test_same_key_is_independent_between_tenants(self):
        from sqlalchemy import func, select
        from src.db.db_models import UsageEvent
        other = MeteringTests()
        other.setUp()
        try:
            self.record("shared-key")
            other.record("shared-key")
            with self.sessions() as session:
                for tenant_id in (self.tenant_id, other.tenant_id):
                    self.assertEqual(session.scalar(select(func.count(UsageEvent.id)).where(
                        UsageEvent.tenant_id == tenant_id,
                    )), 1)
        finally:
            other.tearDown()

    def test_concurrent_quota_and_duplicate(self):
        from src.services.metering import MeteringError
        def run(keys):
            barrier = Barrier(2)
            def work(key):
                barrier.wait(timeout=10)
                try:
                    return self.record(key)
                except MeteringError as error:
                    return error.status_code
            with ThreadPoolExecutor(max_workers=2) as executor:
                return list(executor.map(work, keys))
        results = run(["same", "same"])
        self.assertEqual(results[0], results[1])
        self.assertNotIsInstance(results[0], int)

    def test_concurrent_different_keys(self):
        from src.services.metering import MeteringError
        barrier = Barrier(2)
        def work(key):
            barrier.wait(timeout=10)
            try:
                self.record(key)
                return 200
            except MeteringError as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(work, ["one", "two"])), [200, 429])

    def test_reset_payment_and_tenant_isolation(self):
        from sqlalchemy import select
        from src.db.db_models import Subscription, Tenant, UsageEvent
        from src.services.metering import MeteringError
        self.record("old")
        with self.sessions.begin() as session:
            tenant = session.get(Tenant, self.tenant_id)
            tenant.created_at -= timedelta(days=30)
            event = session.scalar(select(UsageEvent).where(UsageEvent.tenant_id == self.tenant_id))
            event.created_at -= timedelta(days=30)
        self.record("new-period")
        with self.sessions.begin() as session:
            sub = session.scalar(select(Subscription).where(Subscription.tenant_id == self.tenant_id))
            sub.status = "past_due"
        self.record("new-period")  # Historical retries survive status changes.
        with self.assertRaises(MeteringError) as error:
            self.record("blocked")
        self.assertEqual(error.exception.status_code, 402)
        with self.assertRaises(MeteringError) as error:
            self.record("new-period", tenant_id=-1)
        self.assertEqual(error.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
