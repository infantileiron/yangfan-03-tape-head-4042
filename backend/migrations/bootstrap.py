"""Initial schema for a fresh Compose volume."""
from sqlalchemy import inspect, text

from src.models.account import Account
from src.models.audit import Event
from src.models.baseline import Baseline
from src.models.dataset import Dataset
from src.models.reel import RevokedReel
from src.models.review import Review
from src.models.run import Run

SCHEMA = (Account, Dataset, Run, Review, Event, RevokedReel, Baseline)

# Columns added after the first release, applied idempotently to long-lived
# PostgreSQL volumes.  Fresh test databases get them from ``create_all``.
ADDED_COLUMNS = {
    "reviews": {
        "snapshot": "JSON",
    },
}


def _ensure_columns(engine):
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    dialect = engine.dialect.name
    with engine.begin() as connection:
        for table, columns in ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {column["name"] for column in inspector.get_columns(table)}
            for name, column_type in columns.items():
                if name in present:
                    continue
                if dialect == "postgresql":
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {column_type}'))
                else:
                    # SQLite (and others used in tests): add when missing.
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}"))


def migrate(engine):
    tables = [model.__table__ for model in SCHEMA]
    Account.metadata.create_all(engine, tables=tables)
    _ensure_columns(engine)
