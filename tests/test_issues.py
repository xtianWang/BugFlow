import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Issue, ProjectMember, User


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


def create_project(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post(
        "/projects",
        json={"name": "Issue Test Project"},
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


def create_issue(
    client: TestClient,
    project_id: int,
    headers: dict[str, str],
    **data,
):
    payload = {"title": "Test issue", **data}
    return client.post(
        f"/projects/{project_id}/issues",
        json=payload,
        headers=headers,
    )


def test_owner_can_create_issue(client: TestClient):
    owner, owner_headers = auth_headers(client, "issue_owner")
    project = create_project(client, owner_headers)

    response = create_issue(
        client,
        project["id"],
        owner_headers,
        title="Owner issue",
        description="Issue description",
    )

    assert response.status_code == 201
    issue = response.json()
    assert issue["title"] == "Owner issue"
    assert issue["description"] == "Issue description"
    assert issue["status"] == "open"
    assert issue["priority"] == "medium"
    assert issue["creator_id"] == owner["id"]
    assert issue["project_id"] == project["id"]
    assert issue["assignee_id"] is None


def test_member_can_create_issue(client: TestClient):
    _, owner_headers = auth_headers(client, "member_issue_owner")
    member, member_headers = auth_headers(client, "member_issue_user")
    project = create_project(client, owner_headers)
    assert add_member(
        client,
        project["id"],
        member["username"],
        owner_headers,
    ).status_code == 201

    response = create_issue(client, project["id"], member_headers)

    assert response.status_code == 201
    assert response.json()["creator_id"] == member["id"]


def test_outsider_cannot_create_issue(client: TestClient):
    _, owner_headers = auth_headers(client, "outsider_issue_owner")
    project = create_project(client, owner_headers)
    _, outsider_headers = auth_headers(client, "outsider_issue_user")

    response = create_issue(client, project["id"], outsider_headers)

    assert response.status_code == 403


def test_create_issue_with_valid_assignee(client: TestClient):
    _, owner_headers = auth_headers(client, "assignee_owner")
    member, _ = auth_headers(client, "assignee_member")
    project = create_project(client, owner_headers)
    assert add_member(
        client,
        project["id"],
        member["username"],
        owner_headers,
    ).status_code == 201

    response = create_issue(
        client,
        project["id"],
        owner_headers,
        assignee_id=member["id"],
    )

    assert response.status_code == 201
    assert response.json()["assignee_id"] == member["id"]


def test_create_issue_with_non_member_assignee(client: TestClient):
    _, owner_headers = auth_headers(client, "non_member_owner")
    non_member, _ = auth_headers(client, "non_member_user")
    project = create_project(client, owner_headers)

    response = create_issue(
        client,
        project["id"],
        owner_headers,
        assignee_id=non_member["id"],
    )

    assert response.status_code == 400


def test_create_issue_with_missing_assignee(client: TestClient):
    _, owner_headers = auth_headers(client, "missing_assignee_owner")
    project = create_project(client, owner_headers)

    response = create_issue(
        client,
        project["id"],
        owner_headers,
        assignee_id=99999,
    )

    assert response.status_code == 404


def test_create_issue_with_inactive_assignee(
    client: TestClient,
    db_session: Session,
):
    _, owner_headers = auth_headers(client, "inactive_assignee_owner")
    inactive_user, _ = auth_headers(client, "inactive_assignee_user")
    project = create_project(client, owner_headers)
    assert add_member(
        client,
        project["id"],
        inactive_user["username"],
        owner_headers,
    ).status_code == 201

    user = db_session.get(User, inactive_user["id"])
    assert user is not None
    user.is_active = False
    db_session.commit()

    response = create_issue(
        client,
        project["id"],
        owner_headers,
        assignee_id=inactive_user["id"],
    )

    assert response.status_code == 400


def test_unassign_issue(client: TestClient):
    _, owner_headers = auth_headers(client, "unassign_owner")
    member, _ = auth_headers(client, "unassign_member")
    project = create_project(client, owner_headers)
    assert add_member(
        client,
        project["id"],
        member["username"],
        owner_headers,
    ).status_code == 201
    issue = create_issue(
        client,
        project["id"],
        owner_headers,
        assignee_id=member["id"],
    ).json()

    response = client.patch(
        f"/issues/{issue['id']}",
        json={"assignee_id": None},
        headers=owner_headers,
    )

    assert response.status_code == 200
    assert response.json()["assignee_id"] is None


def test_project_members_can_list_issues(client: TestClient):
    _, owner_headers = auth_headers(client, "list_issues_owner")
    member, member_headers = auth_headers(client, "list_issues_member")
    _, outsider_headers = auth_headers(client, "list_issues_outsider")
    project = create_project(client, owner_headers)
    assert add_member(
        client,
        project["id"],
        member["username"],
        owner_headers,
    ).status_code == 201
    issue = create_issue(client, project["id"], owner_headers).json()

    for headers in (owner_headers, member_headers):
        response = client.get(
            f"/projects/{project['id']}/issues",
            headers=headers,
        )
        assert response.status_code == 200
        assert issue["id"] in {item["id"] for item in response.json()}

    assert client.get(
        f"/projects/{project['id']}/issues",
        headers=outsider_headers,
    ).status_code == 403


def test_issue_access_permissions(client: TestClient):
    _, owner_headers = auth_headers(client, "access_issue_owner")
    member, member_headers = auth_headers(client, "access_issue_member")
    _, outsider_headers = auth_headers(client, "access_issue_outsider")
    project = create_project(client, owner_headers)
    assert add_member(
        client,
        project["id"],
        member["username"],
        owner_headers,
    ).status_code == 201
    issue = create_issue(client, project["id"], owner_headers).json()

    assert client.get(f"/issues/{issue['id']}", headers=owner_headers).status_code == 200
    assert client.get(f"/issues/{issue['id']}", headers=member_headers).status_code == 200
    assert client.get(f"/issues/{issue['id']}", headers=outsider_headers).status_code == 403
    assert client.get("/issues/99999", headers=owner_headers).status_code == 404


def test_member_can_update_issue(client: TestClient, db_session: Session):
    _, owner_headers = auth_headers(client, "update_issue_owner")
    member, member_headers = auth_headers(client, "update_issue_member")
    project = create_project(client, owner_headers)
    assert add_member(
        client,
        project["id"],
        member["username"],
        owner_headers,
    ).status_code == 201
    issue = create_issue(client, project["id"], owner_headers).json()

    response = client.patch(
        f"/issues/{issue['id']}",
        json={
            "title": "Updated issue",
            "description": "Updated description",
            "priority": "high",
            "assignee_id": member["id"],
        },
        headers=member_headers,
    )

    assert response.status_code == 200
    updated_issue = response.json()
    assert updated_issue["title"] == "Updated issue"
    assert updated_issue["description"] == "Updated description"
    assert updated_issue["priority"] == "high"
    assert updated_issue["assignee_id"] == member["id"]

    stored_issue = db_session.get(Issue, issue["id"])
    assert stored_issue is not None
    assert stored_issue.title == "Updated issue"
    assert stored_issue.description == "Updated description"
    assert stored_issue.priority == "high"
    assert stored_issue.assignee_id == member["id"]


def test_issue_patch_field_semantics(client: TestClient):
    _, owner_headers = auth_headers(client, "patch_fields_owner")
    member, _ = auth_headers(client, "patch_fields_member")
    project = create_project(client, owner_headers)
    assert add_member(
        client,
        project["id"],
        member["username"],
        owner_headers,
    ).status_code == 201
    issue = create_issue(
        client,
        project["id"],
        owner_headers,
        description="Original description",
        assignee_id=member["id"],
    ).json()

    assert client.patch(
        f"/issues/{issue['id']}",
        json={"title": None},
        headers=owner_headers,
    ).status_code == 422
    clear_description = client.patch(
        f"/issues/{issue['id']}",
        json={"description": None},
        headers=owner_headers,
    )
    assert clear_description.status_code == 200
    assert clear_description.json()["description"] is None
    assert client.patch(
        f"/issues/{issue['id']}",
        json={"priority": "invalid"},
        headers=owner_headers,
    ).status_code == 422
    assert client.patch(
        f"/issues/{issue['id']}",
        json={"priority": None},
        headers=owner_headers,
    ).status_code == 422
    unassign_response = client.patch(
        f"/issues/{issue['id']}",
        json={"assignee_id": None},
        headers=owner_headers,
    )
    assert unassign_response.status_code == 200
    assert unassign_response.json()["assignee_id"] is None

    for forbidden_field in ("status", "creator_id", "project_id"):
        response = client.patch(
            f"/issues/{issue['id']}",
            json={forbidden_field: "unexpected"},
            headers=owner_headers,
        )
        assert response.status_code == 422


def test_valid_status_transitions(client: TestClient):
    _, owner_headers = auth_headers(client, "status_owner")
    member, member_headers = auth_headers(client, "status_member")
    project = create_project(client, owner_headers)
    assert add_member(
        client,
        project["id"],
        member["username"],
        owner_headers,
    ).status_code == 201
    issue = create_issue(client, project["id"], owner_headers).json()

    in_progress = client.patch(
        f"/issues/{issue['id']}/status",
        json={"status": "in_progress"},
        headers=owner_headers,
    )
    assert in_progress.status_code == 200
    assert in_progress.json()["status"] == "in_progress"

    resolved = client.patch(
        f"/issues/{issue['id']}/status",
        json={"status": "resolved"},
        headers=member_headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    closed = client.patch(
        f"/issues/{issue['id']}/status",
        json={"status": "closed"},
        headers=owner_headers,
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"


@pytest.mark.parametrize(
    ("setup_statuses", "invalid_status"),
    [
        ([], "resolved"),
        ([], "closed"),
        (["in_progress"], "open"),
        (["in_progress", "resolved"], "open"),
        (["in_progress", "resolved", "closed"], "open"),
        (["in_progress", "resolved", "closed"], "closed"),
    ],
)
def test_invalid_status_transitions(
    client: TestClient,
    setup_statuses: list[str],
    invalid_status: str,
):
    _, owner_headers = auth_headers(client, "invalid_status_owner")
    project = create_project(client, owner_headers)
    issue = create_issue(client, project["id"], owner_headers).json()

    for next_status in setup_statuses:
        response = client.patch(
            f"/issues/{issue['id']}/status",
            json={"status": next_status},
            headers=owner_headers,
        )
        assert response.status_code == 200

    response = client.patch(
        f"/issues/{issue['id']}/status",
        json={"status": invalid_status},
        headers=owner_headers,
    )

    assert response.status_code == 400


def test_outsider_cannot_update_issue_status(client: TestClient):
    _, owner_headers = auth_headers(client, "status_access_owner")
    project = create_project(client, owner_headers)
    issue = create_issue(client, project["id"], owner_headers).json()
    _, outsider_headers = auth_headers(client, "status_access_outsider")

    response = client.patch(
        f"/issues/{issue['id']}/status",
        json={"status": "in_progress"},
        headers=outsider_headers,
    )

    assert response.status_code == 403


def test_issue_delete_permissions(client: TestClient):
    _, owner_headers = auth_headers(client, "delete_issue_owner")
    member, member_headers = auth_headers(client, "delete_issue_member")
    _, outsider_headers = auth_headers(client, "delete_issue_outsider")
    project = create_project(client, owner_headers)
    assert add_member(
        client,
        project["id"],
        member["username"],
        owner_headers,
    ).status_code == 201
    issue = create_issue(client, project["id"], owner_headers).json()

    assert client.delete(f"/issues/{issue['id']}", headers=member_headers).status_code == 403
    assert client.delete(f"/issues/{issue['id']}", headers=outsider_headers).status_code == 403
    assert client.delete(f"/issues/{issue['id']}", headers=owner_headers).status_code == 200
    assert client.get(f"/issues/{issue['id']}", headers=owner_headers).status_code == 404


def test_delete_project_cascades_issues(
    client: TestClient,
    db_session: Session,
):
    _, owner_headers = auth_headers(client, "issue_cascade_owner")
    member, _ = auth_headers(client, "issue_cascade_member")
    project = create_project(client, owner_headers)
    assert add_member(
        client,
        project["id"],
        member["username"],
        owner_headers,
    ).status_code == 201
    issue = create_issue(client, project["id"], owner_headers).json()

    assert db_session.get(Issue, issue["id"]) is not None
    assert db_session.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project["id"])
    ).all()

    assert client.delete(
        f"/projects/{project['id']}",
        headers=owner_headers,
    ).status_code == 200

    assert db_session.get(Issue, issue["id"]) is None
    assert db_session.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project["id"])
    ).all() == []


def test_create_issue_without_token(client: TestClient):
    _, owner_headers = auth_headers(client, "no_token_issue_owner")
    project = create_project(client, owner_headers)

    response = client.post(
        f"/projects/{project['id']}/issues",
        json={"title": "Unauthenticated issue"},
    )

    assert response.status_code == 401
