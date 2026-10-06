"""
S.T.R.A.N.D — Tests: API Endpoint Integration Tests

Tests the FastAPI endpoints using TestClient.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a FastAPI test client."""
    from strand.api.main import app
    return TestClient(app)


class TestHealthEndpoint:
    """Test the system health check."""

    def test_health_returns_200(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "database" in data

    def test_health_has_version(self, client):
        response = client.get("/api/v1/health")
        data = response.json()
        assert data["version"] == "1.0.0"


class TestRootEndpoint:
    """Test the root redirect."""

    def test_root_redirects_to_docs(self, client):
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 307
        assert "/docs" in response.headers.get("location", "")


class TestAuthMiddleware:
    """Test API key authentication."""

    def test_missing_api_key_401(self, client):
        response = client.get("/api/v1/analysis")
        assert response.status_code == 401

    def test_invalid_api_key_401(self, client):
        response = client.get(
            "/api/v1/analysis",
            headers={"X-API-Key": "invalid-key"},
        )
        assert response.status_code == 401

    def test_valid_api_key_passes(self, client):
        response = client.get(
            "/api/v1/analysis",
            headers={"X-API-Key": "test-api-key"},
        )
        # Should be 200 (may return empty list)
        assert response.status_code == 200


class TestAnalysisEndpoints:
    """Test analysis CRUD endpoints."""

    def test_list_analyses_empty(self, client):
        response = client.get(
            "/api/v1/analysis",
            headers={"X-API-Key": "test-api-key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "analyses" in data

    def test_get_nonexistent_analysis(self, client):
        response = client.get(
            "/api/v1/analysis/nonexistent-id",
            headers={"X-API-Key": "test-api-key"},
        )
        assert response.status_code == 404


class TestSecurityHeaders:
    """Test that security headers are present on all responses."""

    def test_xss_protection(self, client):
        response = client.get("/api/v1/health")
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"

    def test_content_type_nosniff(self, client):
        response = client.get("/api/v1/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_frame_deny(self, client):
        response = client.get("/api/v1/health")
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_attribution_header(self, client):
        response = client.get("/api/v1/health")
        attr = response.headers.get("X-Attribution", "")
        assert "Copernicus" in attr
        assert "OpenStreetMap" in attr

    def test_timing_header(self, client):
        response = client.get("/api/v1/health")
        assert "X-Response-Time-Ms" in response.headers


class TestWebSocket:
    """Test real-time WebSocket progress endpoint."""

    def test_websocket_progress(self, client):
        with client.websocket_connect("/ws/analysis/test-analysis") as ws:
            data = ws.receive_json()
            assert "type" in data
            assert data["analysis_id"] == "test-analysis"
