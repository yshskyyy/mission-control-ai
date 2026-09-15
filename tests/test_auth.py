from types import SimpleNamespace

from app import auth


def _register(client, email: str, name: str) -> dict:
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "secure-password-123", "display_name": name},
    )
    assert response.status_code == 201
    return response.json()


def test_authentication_and_goal_isolation(client, goal_payload, monkeypatch):
    monkeypatch.setattr(auth, "settings", SimpleNamespace(
        auth_disabled=False, jwt_secret="test-secret-with-at-least-32-characters", jwt_expire_minutes=60,
    ))
    alice = _register(client, "alice@example.com", "Alice")
    bob = _register(client, "bob@example.com", "Bob")
    alice_headers = {"Authorization": f"Bearer {alice['access_token']}"}
    bob_headers = {"Authorization": f"Bearer {bob['access_token']}"}

    assert client.get("/api/goals").status_code == 401
    created = client.post("/api/goals", json=goal_payload, headers=alice_headers)
    assert created.status_code == 201
    goal = created.json()
    assert client.get("/api/goals", headers=alice_headers).json()[0]["id"] == goal["id"]
    assert client.get("/api/goals", headers=bob_headers).json() == []
    assert client.get(f"/api/goals/{goal['id']}/plan", headers=bob_headers).status_code == 404


def test_login_rejects_wrong_password(client, monkeypatch):
    monkeypatch.setattr(auth, "settings", SimpleNamespace(
        auth_disabled=False, jwt_secret="test-secret-with-at-least-32-characters", jwt_expire_minutes=60,
    ))
    _register(client, "user@example.com", "User")
    response = client.post(
        "/auth/login", json={"email": "user@example.com", "password": "wrong"}
    )
    assert response.status_code == 401
