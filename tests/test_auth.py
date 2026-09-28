from fastapi.testclient import TestClient


def register_user(
    client: TestClient,
    username: str = "auth_test_user",
    password: str = "securepass123",
):
    return client.post(
        "/auth/register",
        json={"username": username, "password": password},
    )


def login_user(
    client: TestClient,
    username: str = "auth_test_user",
    password: str = "securepass123",
):
    return client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )


def test_register_success(client: TestClient):
    response = register_user(client)

    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "auth_test_user"
    assert "password" not in data
    assert "password_hash" not in data


def test_register_duplicate_username(client: TestClient):
    assert register_user(client).status_code == 201

    response = register_user(client)

    assert response.status_code == 409
    assert response.json()["detail"] == "Username already exists"


def test_register_invalid_username(client: TestClient):
    response = register_user(client, username="ab")

    assert response.status_code == 422


def test_register_invalid_password(client: TestClient):
    response = register_user(client, password="short")

    assert response.status_code == 422


def test_login_success(client: TestClient):
    assert register_user(client).status_code == 201

    response = login_user(client)

    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client: TestClient):
    assert register_user(client).status_code == 201

    response = login_user(client, password="incorrectpass")

    assert response.status_code == 401


def test_login_unknown_user(client: TestClient):
    response = login_user(client, username="unknown_user")

    assert response.status_code == 401


def test_me_success(client: TestClient):
    assert register_user(client).status_code == 201
    login_response = login_user(client)
    token = login_response.json()["access_token"]

    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["username"] == "auth_test_user"


def test_me_without_token(client: TestClient):
    response = client.get("/auth/me")

    assert response.status_code == 401


def test_me_invalid_token(client: TestClient):
    response = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer invalid.token.value"},
    )

    assert response.status_code == 401
