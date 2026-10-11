"""LangGraph checkpointer on the same Postgres, via a small psycopg pool."""

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from sqlalchemy.engine import make_url


def psycopg_conninfo(sqlalchemy_url: str) -> str:
    """`postgresql+psycopg://...` (SQLAlchemy) -> `postgresql://...` (libpq)."""
    return (
        make_url(sqlalchemy_url).set(drivername="postgresql").render_as_string(hide_password=False)
    )


def build_checkpointer(database_url: str) -> tuple[PostgresSaver, ConnectionPool]:
    pool = ConnectionPool(
        psycopg_conninfo(database_url),
        min_size=1,
        max_size=4,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=True,
    )
    saver = PostgresSaver(pool)  # type: ignore[arg-type]
    saver.setup()  # creates/migrates the checkpoint tables (idempotent)
    return saver, pool
