import os
from pathlib import Path

from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
# Test suites commonly point DATABASE_URL at an in-memory or file SQLite. The
# production deployment keeps the PostgreSQL engine configuration below.
if DATABASE_URL.startswith("sqlite"):
    from sqlalchemy.engine.url import make_url

    _url = make_url(DATABASE_URL)
    memory = _url.database in (None, "", ":memory:") or _url.query.get("mode") == "memory"
    if memory:
        engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=240)
Session = sessionmaker(engine, expire_on_commit=False)
redis = Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), socket_timeout=3, socket_connect_timeout=3)
JWT_SECRET = os.getenv("JWT_SECRET", "local-dev-only-secret-please-change-32+")
ARTIFACTS = Path(os.getenv("ARTIFACTS_DIR", "/artifacts"))
SEED_DEMO = os.getenv("SEED_DEMO", "false").lower() == "true"
