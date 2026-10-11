import pytest

from opsagent.settings import Settings


@pytest.mark.parametrize(
    "url",
    [
        "postgres://u:p@ep-x.neon.tech/db?sslmode=require",
        "postgresql://u:p@ep-x.neon.tech/db?sslmode=require",
        "postgresql+psycopg://u:p@ep-x.neon.tech/db?sslmode=require",
    ],
)
def test_hosted_database_urls_get_the_psycopg_driver(url: str) -> None:
    assert Settings(database_url=url).database_url == (
        "postgresql+psycopg://u:p@ep-x.neon.tech/db?sslmode=require"
    )
