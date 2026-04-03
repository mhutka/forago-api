import importlib
import os

from fastapi.testclient import TestClient
from jose import jwt


# Force mock mode for test runs to avoid DB dependency in CI/local smoke checks.
os.environ["DATA_SOURCE_MODE"] = "mock"
os.environ["ENVIRONMENT"] = "development"
os.environ["JWT_SECRET_KEY"] = "test-secret-key"
os.environ["JWT_ALGORITHMS"] = "HS256"

main = importlib.import_module("main")
client = TestClient(main.app)


def auth_headers(user_id: str = "00000000-0000-0000-0000-000000000001"):
    token = jwt.encode({"sub": user_id}, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_health_endpoint_returns_ok():
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["dataSourceMode"] == "mock"


def test_create_find_rejects_invalid_period():
    response = client.post(
        "/api/finds",
        headers=auth_headers(),
        json={
            "date": "2026-03-25T10:00:00Z",
            "categoryPaths": [["nature", "forest"]],
            "description": "Smoke test record",
            "location": {"latitude": 48.14, "longitude": 17.11},
            "clusterHash": "48.14_17.11",
            "period": "INVALID_PERIOD",
        },
    )

    assert response.status_code == 422


def test_private_endpoint_requires_authentication():
    response = client.get("/api/finds/private")
    assert response.status_code == 401


def test_auth_me_returns_subject_from_token():
    user_id = "00000000-0000-0000-0000-000000000222"
    response = client.get("/api/auth/me", headers=auth_headers(user_id))

    assert response.status_code == 200
    assert response.json()["userId"] == user_id


def test_create_and_list_private_finds_with_valid_jwt():
    user_id = "00000000-0000-0000-0000-000000000111"
    create_response = client.post(
        "/api/finds",
        headers=auth_headers(user_id),
        json={
            "date": "2026-03-25T10:00:00Z",
            "categoryPaths": [["nature", "forest"]],
            "description": "Smoke test record",
            "location": {"latitude": 48.14, "longitude": 17.11},
            "clusterHash": "48.14_17.11",
            "period": "MAR_2",
        },
    )

    assert create_response.status_code == 201
    created_id = create_response.json()["id"]

    list_response = client.get("/api/finds/private", headers=auth_headers(user_id))
    assert list_response.status_code == 200
    ids = [item["id"] for item in list_response.json()]
    assert created_id in ids
