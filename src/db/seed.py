from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from src.core.logging import configure_logging, error, info

from .database import Base, engine
from .db_models import Plan, Subscription, Tenant, User


def seed_data(session: Session) -> None:
    """Insert local demo data without overwriting existing plans or subscriptions."""
    session.execute(
        insert(Plan).values([
            {"name": "Free", "api_call_limit": 1000, "token_limit": 100000},
            {"name": "Pro", "api_call_limit": 10000, "token_limit": 1000000},
        ]).on_conflict_do_nothing(index_elements=["name"])
    )
    free_plan = session.scalars(select(Plan).where(Plan.name == "Free")).one()
    tenant = session.scalars(select(Tenant).where(Tenant.name == "Capstone Demo")).one_or_none()
    if tenant is None:
        tenant = Tenant(name="Capstone Demo")
        session.add(tenant)
        session.flush()

    if tenant.subscription is None:
        subscription = Subscription(tenant=tenant, plan=free_plan, status="active")
        # Initialize the first window using one clock: the stored signup time.
        subscription.set_quota_period(tenant.created_at, at=tenant.created_at)
        session.add(subscription)

    user = session.scalars(
        select(User).where(User.tenant_id == tenant.id, User.name == "Demo User")
    ).one_or_none()
    if user is None:
        session.add(User(tenant=tenant, name="Demo User"))


def initialize_database() -> None:
    """Create missing tables and seed data in one PostgreSQL transaction."""
    with engine.begin() as connection:
        # Serialize this setup command, including its create-table checks.
        connection.execute(text("SELECT pg_advisory_xact_lock(7349201)"))
        Base.metadata.create_all(connection)
        with Session(bind=connection) as session:
            seed_data(session)
            session.flush()


if __name__ == "__main__":
    configure_logging()
    try:
        initialize_database()
    except OperationalError:
        error(__name__, "Database unavailable during seeding")
        raise SystemExit("Database temporarily unavailable. Check PostgreSQL connectivity.") from None
    finally:
        engine.dispose()
    info(__name__, "Tables ready; demo data seeded")
