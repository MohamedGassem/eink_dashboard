from fastapi.testclient import TestClient

from eink_dashboard.main import app

# Le détail par fournisseur de `/health` est couvert par
# tests/unit/test_api_dashboard.py, qui monte l'état sans lifespan.


def test_liveness_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
