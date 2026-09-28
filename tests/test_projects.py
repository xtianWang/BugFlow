from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProjectMember


def register_user(
    client: TestClient,
    username: str,
    password: str = "securepass123",
) -> dict:
    response = client.post(
        "/auth/register",
        json={"username": username, "password": password},
    )
    assert response.status_code == 201
    return response.json()


def login_user(
    client: TestClient,
    username: str,
    password: str = "securepass123",
) -> dict:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()


def auth_headers(client: TestClient, username: str) -> tuple[dict, dict[str, str]]:
    user = register_user(client, username)
    token = login_user(client, username)["access_token"]
    return user, {"Authorization": f"Bearer {token}"}


def create_project(
    client: TestClient,
    headers: dict[str, str],
    name: str = "Test Project",
    description: str | None = "Test description",
) -> dict:
    response = client.post(
        "/projects",
        json={"name": name, "description": description},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def add_member(
    client: TestClient,
    project_id: int,
    username: str,
    headers: dict[str, str],
):
    return client.post(
        f"/projects/{project_id}/members",
        json={"username": username},
        headers=headers,
    )


def test_create_project(client: TestClient, db_session: Session):
    owner, owner_headers = auth_headers(client, "project_owner")

    response = client.post(
        "/projects",
        json={"name": "BugFlow", "description": "Project description"},
        headers=owner_headers,
    )

    assert response.status_code == 201
    project = response.json()
    assert project["name"] == "BugFlow"
    assert project["description"] == "Project description"
    assert project["owner_id"] == owner["id"]
    assert db_session.get(ProjectMember, (project["id"], owner["id"])) is not None


def test_create_project_without_token(client: TestClient):
    response = client.post("/projects", json={"name": "No Token"})

    assert response.status_code == 401


def test_owner_can_list_own_project(client: TestClient):
    _, owner_headers = auth_headers(client, "list_owner")
    project = create_project(client, owner_headers, name="Owned Project")

    response = client.get("/projects", headers=owner_headers)

    assert response.status_code == 200
    assert project["id"] in {item["id"] for item in response.json()}


def test_outsider_cannot_access_project(client: TestClient):
    _, owner_headers = auth_headers(client, "outsider_owner")
    project = create_project(client, owner_headers)
    _, outsider_headers = auth_headers(client, "outsider_user")

    list_response = client.get("/projects", headers=outsider_headers)
    assert list_response.status_code == 200
    assert project["id"] not in {item["id"] for item in list_response.json()}

    assert client.get(f"/projects/{project['id']}", headers=outsider_headers).status_code == 403
    assert client.patch(
        f"/projects/{project['id']}",
        json={"name": "Unauthorized"},
        headers=outsider_headers,
    ).status_code == 403
    assert client.delete(
        f"/projects/{project['id']}",
        headers=outsider_headers,
    ).status_code == 403


def test_owner_can_add_member(client: TestClient):
    _, owner_headers = auth_headers(client, "member_owner")
    member, _ = auth_headers(client, "member_user")
    project = create_project(client, owner_headers)

    response = add_member(client, project["id"], member["username"], owner_headers)

    assert response.status_code == 201
    assert response.json()["user_id"] == member["id"]
    assert response.json()["is_owner"] is False

    members_response = client.get(
        f"/projects/{project['id']}/members",
        headers=owner_headers,
    )
    assert members_response.status_code == 200
    members_by_id = {item["user_id"]: item for item in members_response.json()}
    assert members_by_id[member["id"]]["is_owner"] is False
    assert members_by_id[project["owner_id"]]["is_owner"] is True


def test_add_duplicate_member(client: TestClient):
    _, owner_headers = auth_headers(client, "duplicate_owner")
    member, _ = auth_headers(client, "duplicate_user")
    project = create_project(client, owner_headers)

    assert add_member(
        client,
        project["id"],
        member["username"],
        owner_headers,
    ).status_code == 201
    response = add_member(client, project["id"], member["username"], owner_headers)

    assert response.status_code == 409


def test_member_access_permissions(client: TestClient):
    _, owner_headers = auth_headers(client, "permission_owner")
    member, member_headers = auth_headers(client, "permission_member")
    project = create_project(client, owner_headers)
    assert add_member(
        client,
        project["id"],
        member["username"],
        owner_headers,
    ).status_code == 201

    assert client.get("/projects", headers=member_headers).status_code == 200
    assert client.get(
        f"/projects/{project['id']}",
        headers=member_headers,
    ).status_code == 200
    assert client.get(
        f"/projects/{project['id']}/members",
        headers=member_headers,
    ).status_code == 200
    assert client.patch(
        f"/projects/{project['id']}",
        json={"name": "Member update"},
        headers=member_headers,
    ).status_code == 403
    assert client.delete(
        f"/projects/{project['id']}",
        headers=member_headers,
    ).status_code == 403
    assert add_member(
        client,
        project["id"],
        "permission_owner",
        member_headers,
    ).status_code == 403
    assert client.delete(
        f"/projects/{project['id']}/members/{member['id']}",
        headers=member_headers,
    ).status_code == 403


def test_owner_can_update_project(client: TestClient):
    _, owner_headers = auth_headers(client, "update_owner")
    project = create_project(client, owner_headers, description="Initial description")

    name_response = client.patch(
        f"/projects/{project['id']}",
        json={"name": "Renamed Project"},
        headers=owner_headers,
    )
    assert name_response.status_code == 200
    assert name_response.json()["name"] == "Renamed Project"
    assert name_response.json()["description"] == "Initial description"

    description_response = client.patch(
        f"/projects/{project['id']}",
        json={"description": "Updated description"},
        headers=owner_headers,
    )
    assert description_response.status_code == 200
    assert description_response.json()["description"] == "Updated description"

    clear_response = client.patch(
        f"/projects/{project['id']}",
        json={"description": None},
        headers=owner_headers,
    )
    assert clear_response.status_code == 200
    assert clear_response.json()["description"] is None


def test_project_name_cannot_be_null(client: TestClient):
    _, owner_headers = auth_headers(client, "null_name_owner")
    project = create_project(client, owner_headers)

    response = client.patch(
        f"/projects/{project['id']}",
        json={"name": None},
        headers=owner_headers,
    )

    assert response.status_code == 422


def test_owner_cannot_remove_self(client: TestClient):
    owner, owner_headers = auth_headers(client, "self_remove_owner")
    project = create_project(client, owner_headers)

    response = client.delete(
        f"/projects/{project['id']}/members/{owner['id']}",
        headers=owner_headers,
    )

    assert response.status_code == 400


def test_owner_can_remove_member(client: TestClient):
    _, owner_headers = auth_headers(client, "remove_owner")
    member, member_headers = auth_headers(client, "remove_member")
    project = create_project(client, owner_headers)
    assert add_member(
        client,
        project["id"],
        member["username"],
        owner_headers,
    ).status_code == 201

    response = client.delete(
        f"/projects/{project['id']}/members/{member['id']}",
        headers=owner_headers,
    )

    assert response.status_code == 200
    assert client.get(
        f"/projects/{project['id']}",
        headers=member_headers,
    ).status_code == 403
    list_response = client.get("/projects", headers=member_headers)
    assert list_response.status_code == 200
    assert project["id"] not in {item["id"] for item in list_response.json()}


def test_owner_can_delete_project(client: TestClient):
    _, owner_headers = auth_headers(client, "delete_owner")
    project = create_project(client, owner_headers)

    response = client.delete(f"/projects/{project['id']}", headers=owner_headers)

    assert response.status_code == 200
    assert client.get(
        f"/projects/{project['id']}",
        headers=owner_headers,
    ).status_code == 404


def test_delete_project_cascades_project_members(
    client: TestClient,
    db_session: Session,
):
    _, owner_headers = auth_headers(client, "cascade_owner")
    member, _ = auth_headers(client, "cascade_member")
    project = create_project(client, owner_headers)
    assert add_member(
        client,
        project["id"],
        member["username"],
        owner_headers,
    ).status_code == 201

    memberships_before_delete = db_session.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project["id"])
    ).all()
    assert {membership.user_id for membership in memberships_before_delete} == {
        project["owner_id"],
        member["id"],
    }

    assert client.delete(
        f"/projects/{project['id']}",
        headers=owner_headers,
    ).status_code == 200

    memberships_after_delete = db_session.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project["id"])
    ).all()
    assert memberships_after_delete == []
