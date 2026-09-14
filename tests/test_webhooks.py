import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import patch
from uuid import uuid4


@unittest.skipUnless(os.getenv("RUN_DB_TESTS") == "1", "Requires configured PostgreSQL")
class WebhookTests(unittest.TestCase):
    def setUp(self):
        from test_api import APITests
        from sqlalchemy import select
        from src.db.db_models import Plan, Tenant
        self.api = APITests()
        self.api.setUp()
        self.addCleanup(self.api.tearDown)
        self.customer = "cus_" + uuid4().hex
        with self.api.fixture.sessions.begin() as session:
            session.get(Tenant, self.api.fixture.tenant_id).stripe_customer_id = self.customer
            self.pro_id = session.scalar(select(Plan.id).where(Plan.name == "Pro"))
        self.assertIsNotNone(self.pro_id, "Seed Free and Pro before integration tests")
        self.events = []
        self.addCleanup(self.clean_events)
        self.config = patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_fixture",
            "STRIPE_PRO_PRICE_ID": "price_fixture", "STRIPE_WEBHOOK_SECRET": "whsec_fixture"})
        self.config.start()
        self.addCleanup(self.config.stop)
        self.provider = patch("src.services.webhooks.StripeClient")
        self.remote = self.provider.start().return_value.v1.subscriptions.list
        self.addCleanup(self.provider.stop)
        self.set_remote("active")

    def clean_events(self):
        from sqlalchemy import delete
        from src.db.db_models import StripeEvent
        with self.api.fixture.sessions.begin() as session:
            session.execute(delete(StripeEvent).where(StripeEvent.id.in_(self.events)))

    def set_remote(self, status, subscription_id="sub_fixture", created=1):
        from stripe import Subscription
        data = {"id": subscription_id, "created": created, "status": status,
                "customer": self.customer, "livemode": False,
                "metadata": {"tenant_id": str(self.api.fixture.tenant_id)},
                "items": {"data": [{"price": {"id": "price_fixture"}, "quantity": 1}]}}
        self.remote.return_value.auto_paging_iter.return_value = [Subscription.construct_from(data, "sk_test_fixture")]

    def event(self, kind="customer.subscription.updated"):
        event_id = "evt_" + uuid4().hex
        self.events.append(event_id)
        return {"id": event_id, "object": "event", "type": kind, "livemode": False,
                "data": {"object": {"id": "sub_fixture", "customer": self.customer,
                                     "mode": "subscription", "status": "active"}}}

    def send(self, event, timestamp=None, tamper=False):
        payload = json.dumps(event).encode()
        timestamp = int(time.time()) if timestamp is None else timestamp
        digest = hmac.new(b"whsec_fixture", str(timestamp).encode() + b"." + payload, hashlib.sha256).hexdigest()
        return self.api.client.post("/stripe/webhook", content=payload + (b" " if tamper else b""),
                                    headers={"Stripe-Signature": f"t={timestamp},v1={digest}"})

    def snapshot(self):
        from sqlalchemy import select
        from src.db.db_models import Subscription
        with self.api.fixture.sessions() as session:
            sub = session.scalar(select(Subscription).where(Subscription.tenant_id == self.api.fixture.tenant_id))
            return sub.plan_id, sub.status, sub.stripe_subscription_id, sub.period_start, sub.period_end

    def test_signed_upgrade_duplicate_and_period_preservation(self):
        before = self.snapshot()
        event = self.event("checkout.session.completed")
        response = self.send(event)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.snapshot()[:3], (self.pro_id, "active", "sub_fixture"))
        self.assertEqual(self.snapshot()[3:], before[3:])
        self.assertEqual(self.send(event).status_code, 200)
        self.remote.assert_called_once()
        from sqlalchemy import select, func
        from src.db.db_models import StripeEvent
        with self.api.fixture.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(StripeEvent).where(StripeEvent.id == event["id"])), 1)

    def test_bad_signature_expiry_and_live_event(self):
        before = self.snapshot()
        event = self.event()
        self.assertEqual(self.send(event, tamper=True).status_code, 400)
        self.assertEqual(self.send(event, timestamp=int(time.time()) - 600).status_code, 400)
        self.assertEqual(self.api.client.post("/stripe/webhook", content=b"{}").status_code, 400)
        event["livemode"] = True
        self.assertEqual(self.send(event).status_code, 400)
        self.remote.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_concurrent_duplicate(self):
        from concurrent.futures import ThreadPoolExecutor
        event = self.event()
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: self.send(event), range(2)))
        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.remote.assert_called_once()

    def test_delayed_event_uses_current_state_and_cancellation_blocks_usage(self):
        self.set_remote("canceled", "sub_newer", created=2)
        response = self.send(self.event())  # Payload still says active on an older subscription.
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.snapshot()[:3], (self.pro_id, "canceled", "sub_newer"))
        result = self.api.client.post("/generate", headers=self.api.headers, json=self.api.body)
        self.assertEqual(result.status_code, 402)

    def test_provider_failure_rolls_back_and_retry_succeeds(self):
        from stripe import APIConnectionError
        from src.db.db_models import StripeEvent
        before = self.snapshot()
        event = self.event()
        self.remote.side_effect = APIConnectionError("private provider details")
        response = self.send(event)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private", response.text)
        self.assertEqual(self.snapshot(), before)
        with self.api.fixture.sessions() as session:
            self.assertIsNone(session.get(StripeEvent, event["id"]))
        self.remote.side_effect = None
        self.assertEqual(self.send(event).status_code, 200)

    def test_customer_binding_and_price_mismatch(self):
        before = self.snapshot()
        event = self.event()
        event["data"]["object"]["customer"] = "cus_unknown"
        self.assertEqual(self.send(event).status_code, 503)
        self.remote.assert_not_called()
        self.remote.return_value.auto_paging_iter.return_value[0]["items"]["data"][0]["price"]["id"] = "price_other"
        self.assertEqual(self.send(self.event()).status_code, 503)
        self.assertEqual(self.snapshot(), before)
