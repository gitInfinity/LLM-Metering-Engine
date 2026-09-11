import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from psycopg.errors import ConnectionTimeout
from dotenv import load_dotenv
from src.core.logging import configure_logging, error, info

load_dotenv()  # Load environment variables from .env file if present

class Base(DeclarativeBase):
    """Base class for database ORM models, separate from Pydantic API models."""


database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is required. Load your .env file before importing src.db.database.")

url = make_url(database_url)
if url.drivername == "postgresql":
    url = url.set(drivername="postgresql+psycopg")

engine = create_engine(url, connect_args={"connect_timeout": 5})
SessionLocal = sessionmaker(bind=engine)


if __name__ == "__main__":
    configure_logging()
    try:
        with SessionLocal.begin() as session:
            if session.scalar(text("SELECT 1")) != 1:
                raise RuntimeError("Unexpected database health check result.")
    except OperationalError as exc:
        error(__name__, "PostgreSQL health check failed")
        if not isinstance(exc.orig, ConnectionTimeout):
            raise SystemExit("PostgreSQL connection failed. Check database availability and credentials.") from None
        raise SystemExit(
            f"PostgreSQL connection timed out at {url.host}:{url.port or 5432}. "
            "For the local Docker setup, start Docker Desktop, then run "
            "'docker compose up -d --wait db'. Check 'docker compose ps db' "
            "and confirm DATABASE_URL matches the published database port."
        ) from None
    finally:
        engine.dispose()
    info(__name__, "PostgreSQL connection successful.")
