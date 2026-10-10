"""Unit tests for FastAPI REST API endpoints."""

from fastapi.testclient import TestClient
from src.api.app import app

client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "version" in data


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "formulir" in data["supported_documents"]
    assert "ppkr" in data["supported_documents"]


def test_schema_endpoint():
    response = client.get("/api/v1/schemas/cross_check_report")
    assert response.status_code == 200
    data = response.json()
    assert "properties" in data
    assert "$defs" in data or "definitions" in data or "title" in data


def test_evaluate_no_files_returns_400():
    response = client.post("/api/v1/evaluate")
    assert response.status_code == 400
    assert "Minimal satu berkas" in response.json()["detail"]


def test_evaluate_paths_invalid_path():
    response = client.post(
        "/api/v1/evaluate-paths",
        json={"documents": {"formulir": ["/non/existent/path/formulir.pdf"]}},
    )
    assert response.status_code == 400
    assert "tidak ditemukan" in response.json()["detail"]
