"""Phase 0 application health contracts."""

from fastapi.testclient import TestClient

from apps.api.main import create_app


def test_live_endpoint_is_always_available() -> None:
    response = TestClient(create_app()).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_ready_endpoint_fails_closed_without_database_configuration() -> None:
    response = TestClient(create_app()).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_spa_routes_fall_back_to_the_built_web_shell() -> None:
    client = TestClient(create_app())

    for path in ("/", "/runs/demo", "/evals"):
        response = client.get(path)
        assert response.status_code == 200
        assert "CommerceAgent" in response.text
