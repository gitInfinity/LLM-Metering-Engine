import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

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
    try:
        with SessionLocal.begin() as session:
            if session.scalar(text("SELECT 1")) != 1:
                raise RuntimeError("Unexpected database health check result.")
    finally:
        engine.dispose()
    print("PostgreSQL connection successful.")
