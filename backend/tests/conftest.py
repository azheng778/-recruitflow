from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


if os.getenv("DB_NAME") != os.getenv("TEST_DB_NAME", "hr_recruitment_test"):
    raise RuntimeError("Tests require DB_NAME to equal TEST_DB_NAME")

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def hr_client(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "hr_demo", "password": os.getenv("DEMO_PASSWORD") or "RecruitFlow!2026"},
    )
    assert response.status_code == 200, response.text
    client.headers.update({"X-CSRF-Token": client.cookies.get("csrf_token")})
    return client


@pytest.fixture
def interviewer_client(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "interviewer_demo", "password": os.getenv("DEMO_PASSWORD") or "RecruitFlow!2026"},
    )
    assert response.status_code == 200, response.text
    client.headers.update({"X-CSRF-Token": client.cookies.get("csrf_token")})
    return client
