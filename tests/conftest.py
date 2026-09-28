import os

os.environ["BUGFLOW_SECRET_KEY"] = "bugflow-test-secret-not-for-production"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
import app.models  # noqa: F401
from app.main import app


test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def override_get_db():
    with Session(test_engine) as session:
        yield session


@pytest.fixture
def client():
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session(client):
    with Session(test_engine) as session:
        yield session
