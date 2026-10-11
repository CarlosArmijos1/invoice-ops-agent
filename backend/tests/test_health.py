from fastapi.testclient import TestClient

from opsagent.api.main import create_app
from opsagent.settings import Environment, Settings


def test_health_reports_ok_and_environment() -> None:
    client = TestClient(create_app(Settings(environment=Environment.TEST)))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["environment"] == "test"
