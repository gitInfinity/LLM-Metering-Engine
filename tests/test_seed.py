import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

with patch.dict(os.environ, {
    "DATABASE_URL": os.getenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test"),
}):
    from src.db.db_models import Plan, Tenant
    from src.db.seed import seed_data


class SeedTests(unittest.TestCase):
    def test_first_period_uses_signup_when_database_clock_is_ahead(self):
        signup = datetime(2026, 9, 11, 12, tzinfo=UTC)
        tenant = Tenant(id=1, name="Capstone Demo", created_at=signup)
        plan = Plan(id=1, name="Free", api_call_limit=1000, token_limit=100000)
        session = MagicMock()
        session.scalars.return_value.one.return_value = plan
        session.scalars.return_value.one_or_none.side_effect = [tenant, None]

        with patch("src.db.periods.datetime", wraps=datetime) as clock:
            clock.now.return_value = signup - timedelta(seconds=5)
            seed_data(session)

        self.assertEqual(tenant.subscription.period_start, signup)
        self.assertEqual(tenant.subscription.period_end, signup + timedelta(days=30))


if __name__ == "__main__":
    unittest.main()
