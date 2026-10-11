"""Integration fixtures backed by a real Postgres.

- A dedicated `<db>_test` database is created and migrated with Alembic once
  per session, so the migrations themselves are exercised by the tests.
- Each test runs inside a transaction that is rolled back afterwards.
- Without a reachable database the tests are skipped locally, but they fail in
  CI (`REQUIRE_DB=1`) so a broken setup can never pass silently.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from opsagent.settings import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _test_database_url() -> str:
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


def _ensure_database(url: str) -> None:
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    url = _test_database_url()
    try:
        _ensure_database(url)
    except OperationalError as exc:
        if os.environ.get("REQUIRE_DB") == "1":
            raise
        pytest.skip(
            f"Postgres not reachable ({exc.__class__.__name__}); run `docker compose up -d db`"
        )

    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def session_factory(db_engine: Engine) -> Iterator[sessionmaker[Session]]:
    """Sessions that commit into savepoints of one outer transaction, rolled back at the end.

    Lets code under test use its own sessions and `session.begin()` blocks
    exactly as in production, while each test still starts from a clean DB.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    try:
        yield sessionmaker(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
    finally:
        transaction.rollback()
        connection.close()
