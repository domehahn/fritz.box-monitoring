"""Unit tests for secured Device Manager Web Application."""
import base64
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


def test_device_manager_invalid_username_rejected(client):
    with patch("fritz_monitoring.device_manager.app.ADMIN_PASSWORD", "secret123"):
        headers = {
            "Authorization": "Basic "
            + base64.b64encode(b"wrong_user:secret123").decode("utf-8")
        }
        resp = client.get("/", headers=headers)
        assert resp.status_code == 401


def test_device_manager_authenticated_access(client):
    with patch("fritz_monitoring.device_manager.app.ADMIN_PASSWORD", "secret123"):
        with patch(
            "fritz_monitoring.device_manager.app.get_fritz_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.get_all_hosts.return_value = [
                {"name": "Phone", "status": True, "mac": "00:11:22:33:44:55"}
            ]
            mock_get_client.return_value = mock_client

            headers = {
                "Authorization": "Basic "
                + base64.b64encode(b"admin:secret123").decode("utf-8")
            }
            resp = client.get("/", headers=headers)
            assert resp.status_code == 200


def _basic(user: str = "admin", pw: str = "secret123") -> dict:
    token = base64.b64encode(f"{user}:{pw}".encode()).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


def test_session_csrf_protection_failure(client):
    """A session-authenticated POST without a matching CSRF token is rejected."""
    with patch("fritz_monitoring.device_manager.app.ADMIN_PASSWORD", "secret123"):
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["csrf_token"] = "expected-token"

        resp = client.post(
            "/api/device/delete/00:11:22:33:44:55",
            headers={"X-CSRF-Token": "wrong-token"},
        )
        assert resp.status_code == 400
        assert "CSRF validation failed" in resp.json["error"]


def test_basic_auth_delete_skips_csrf(client):
    """HTTP Basic auth clients are not cookie-driven, so CSRF does not apply."""
    with patch("fritz_monitoring.device_manager.app.ADMIN_PASSWORD", "secret123"):
        with patch(
            "fritz_monitoring.device_manager.app.get_fritz_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            resp = client.post(
                "/api/device/delete/00:11:22:33:44:55",
                headers={**_basic(), "Accept": "application/json"},
            )
            assert resp.status_code == 200
            assert resp.json["success"] is True
            mock_client.admin.delete_host.assert_called_once_with("00:11:22:33:44:55")


def _fake_mesh():
    router = MagicMock(
        name="fritz.box",
        mac="00:11:22:33:44:55",
        ip="192.168.178.1",
        is_router=True,
        is_repeater=False,
        is_powerline=False,
        parent_node=None,
        extra={"active": True},
    )
    router.name = "fritz.box"
    rep = MagicMock(
        mac="AA:BB:CC:DD:EE:FF",
        ip="192.168.178.2",
        is_router=False,
        is_repeater=True,
        is_powerline=False,
        parent_node="fritz.box",
        extra={"active": True, "link_rx_kbps": 300000},
    )
    rep.name = "Repeater-OG"
    mesh = MagicMock()
    mesh.nodes = (router, rep)
    dev = MagicMock(connected_to="Repeater-OG")
    mesh.devices = (dev,)
    return mesh


@pytest.mark.parametrize("route", ["/topology", "/graph", "/api/topology"])
def test_topology_and_graph_routes_render(client, route):
    with patch("fritz_monitoring.device_manager.app.ADMIN_PASSWORD", "secret123"):
        with patch(
            "fritz_monitoring.device_manager.app.get_fritz_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.discover_mesh.return_value = _fake_mesh()
            mock_client.get_all_hosts.return_value = [
                {"status": True, "mac": "11:11:11:11:11:11"}
            ]
            mock_get_client.return_value = mock_client

            resp = client.get(route, headers=_basic())
            assert resp.status_code == 200
            if route == "/api/topology":
                body = resp.get_json()
                assert len(body["nodes"]) == 2
                assert body["links"] == [
                    {
                        "source": "00:11:22:33:44:55",
                        "target": "AA:BB:CC:DD:EE:FF",
                        "type": "mesh",
                    }
                ]
                assert body["nodes"][1]["connected_devices"] == 1


def test_login_establishes_session_and_delete_works(client):
    """Full browser flow: login form -> session -> CSRF-protected delete succeeds."""
    with patch("fritz_monitoring.device_manager.app.ADMIN_PASSWORD", "secret123"):
        with patch(
            "fritz_monitoring.device_manager.app.get_fritz_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.get_all_hosts.return_value = []
            mock_get_client.return_value = mock_client

            # Unauthenticated browser navigation is redirected to /login.
            resp = client.get("/", headers={"Accept": "text/html"})
            assert resp.status_code == 302
            assert "/login" in resp.headers["Location"]

            # Wrong credentials -> 401 + login page re-rendered.
            bad = client.post("/login", data={"username": "admin", "password": "nope"})
            assert bad.status_code == 401

            # Correct credentials -> session established.
            ok = client.post(
                "/login", data={"username": "admin", "password": "secret123"}
            )
            assert ok.status_code == 302

            with client.session_transaction() as sess:
                assert sess["authenticated"] is True
                csrf = sess["csrf_token"]

            # Delete via browser form (session cookie + hidden csrf field).
            deleted = client.post(
                "/api/devices/delete-offline", data={"csrf_token": csrf}
            )
            assert deleted.status_code == 302  # redirected back to index with flash

            # Logout clears the session.
            client.post("/logout", data={"csrf_token": csrf})
            with client.session_transaction() as sess:
                assert "authenticated" not in sess
