"""Unit tests for secured Device Manager Web Application."""
import pytest
from unittest.mock import patch, MagicMock
from fritz_monitoring.device_manager.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_device_manager_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.data.decode("utf-8") == "OK"
    assert resp.headers.get("Content-Security-Policy") == "default-src 'self'"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"


def test_device_manager_unauthenticated_access(client):
    with patch("fritz_monitoring.device_manager.app.ADMIN_PASSWORD", "secret123"):
        resp = client.get("/")
        assert resp.status_code == 401


def test_device_manager_authenticated_access(client):
    with patch("fritz_monitoring.device_manager.app.ADMIN_PASSWORD", "secret123"):
        with patch("fritz_monitoring.device_manager.app.get_fritz_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.get_all_hosts.return_value = [{"name": "Phone", "status": True, "mac": "00:11:22:33:44:55"}]
            mock_get_client.return_value = mock_client

            # HTTP Basic auth
            import base64
            headers = {
                "Authorization": "Basic " + base64.b64encode(b"admin:secret123").decode("utf-8")
            }
            resp = client.get("/", headers=headers)
            assert resp.status_code == 200


def test_device_manager_csrf_protection_failure(client):
    with patch("fritz_monitoring.device_manager.app.ADMIN_PASSWORD", "secret123"):
        import base64
        headers = {
            "Authorization": "Basic " + base64.b64encode(b"admin:secret123").decode("utf-8")
        }
        # POST without CSRF token
        resp = client.post("/api/device/delete/00:11:22:33:44:55", headers=headers)
        assert resp.status_code == 400
        assert "CSRF validation failed" in resp.json["error"]

