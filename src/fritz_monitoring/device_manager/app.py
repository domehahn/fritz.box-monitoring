#!/usr/bin/env python3
"""
Fritz!Box Device Management Web Interface (Secured)
Provides authenticated device viewing, topology representation, and hardened deletion operations.
"""
from __future__ import annotations
import os
import re
import json
import uuid
import time
import secrets
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from functools import wraps
from typing import Callable, Any, Dict, List
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    session,
    abort,
    redirect,
    url_for,
    flash,
    Response,
)
from loguru import logger

from fritz_avm_client import FritzClient, Settings as FritzSettings
from ..config import Settings

app = Flask(__name__)


def resolve_secret_key() -> str:
    """Resolve Flask secret key from file or environment. Fail fast if unconfigured."""
    secret_key_file = os.getenv("DEVICE_MANAGER_SECRET_KEY_FILE")
    if secret_key_file:
        if os.path.exists(secret_key_file):
            try:
                with open(secret_key_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        return content
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to read DEVICE_MANAGER_SECRET_KEY_FILE '{secret_key_file}': {exc}"
                ) from exc
        else:
            raise RuntimeError(
                f"DEVICE_MANAGER_SECRET_KEY_FILE specified ('{secret_key_file}') but file does not exist"
            )

    env_key = os.getenv("SECRET_KEY")
    if env_key:
        return env_key

    # Non-production fallback warning
    if os.getenv("FLASK_ENV") == "production":
        raise RuntimeError(
            "Production mode requires DEVICE_MANAGER_SECRET_KEY_FILE or SECRET_KEY environment variable"
        )
    return "dev-secret-key-change-in-production-123456789"


app.config["SECRET_KEY"] = resolve_secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv(
    "SESSION_COOKIE_SECURE", "false"
).lower() in ("true", "1")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
    hours=int(os.getenv("SESSION_LIFETIME_HOURS", "8"))
)

settings = Settings()
ADMIN_USERNAME = os.getenv("DEVICE_MANAGER_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = settings.resolved_device_manager_admin_password

MAC_REGEX = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")

# Simple sliding window rate limiter: IP -> list of timestamps
_rate_limits: Dict[str, List[float]] = defaultdict(list)
RATE_LIMIT_WINDOW = 60.0  # seconds
MAX_REQUESTS_PER_WINDOW = 20


def check_rate_limit() -> bool:
    """Rate limit POST requests per remote IP address."""
    ip = request.remote_addr or "unknown"
    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW
    _rate_limits[ip] = [t for t in _rate_limits[ip] if t > window_start]
    if len(_rate_limits[ip]) >= MAX_REQUESTS_PER_WINDOW:
        return False
    _rate_limits[ip].append(now)
    return True


@app.after_request
def apply_security_headers(response: Response) -> Response:
    """Attach HTTP security headers to all responses."""
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


def get_fritz_client() -> FritzClient:
    """Create FritzClient instance from configuration."""
    fritz_settings = FritzSettings(
        fritz_host=settings.fritz_host,
        fritz_port=settings.fritz_port,
        fritz_username=settings.fritz_username,
        fritz_password=settings.resolved_password,
        fritz_password_file=settings.fritz_password_file,
        fritz_use_tls=settings.fritz_use_tls,
        fritz_timeout=settings.fritz_timeout,
    )
    return FritzClient(fritz_settings)


def _wants_json() -> bool:
    """Heuristic: does this client expect a JSON response rather than an HTML page?"""
    if request.is_json or request.headers.get("X-CSRF-Token"):
        return True
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    accept = request.accept_mimetypes
    return bool(accept["application/json"]) and not accept.accept_html


def _check_admin_credentials(username: str | None, password: str | None) -> bool:
    """Constant-time credential comparison against the configured admin identity."""
    if not ADMIN_PASSWORD or username is None or password is None:
        return False
    user_ok = secrets.compare_digest(username, ADMIN_USERNAME)
    pass_ok = secrets.compare_digest(password, ADMIN_PASSWORD)
    return user_ok and pass_ok


def require_auth(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator enforcing authentication via HTTP Basic auth or an established session."""

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if not ADMIN_PASSWORD:
            logger.error(
                "Device Manager accessed but DEVICE_MANAGER_ADMIN_PASSWORD(_FILE) is not configured"
            )
            return abort(
                503,
                description="Device Manager disabled: Admin password not configured",
            )

        auth = request.authorization
        if auth and _check_admin_credentials(auth.username, auth.password):
            return f(*args, **kwargs)

        if session.get("authenticated"):
            return f(*args, **kwargs)

        # Real browsers send a literal "text/html" in Accept and get the login
        # page; API/CLI clients (curl's */*, fetch, tests) get a 401.
        if "text/html" in request.headers.get("Accept", "") and not _wants_json():
            return redirect(url_for("login", next=request.full_path))
        return (
            jsonify({"error": "Unauthorized: Valid admin credentials required"}),
            401,
            {"WWW-Authenticate": 'Basic realm="Fritz Device Manager"'},
        )

    return decorated


def validate_csrf(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator validating CSRF token for state-changing POST requests."""

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if request.method == "POST":
            if not check_rate_limit():
                return jsonify({"error": "Rate limit exceeded"}), 429

            # Requests authenticated purely via HTTP Basic auth are not
            # cookie-driven, so a cross-site form/JS cannot forge them. CSRF
            # tokens only matter for session-cookie authenticated browsers.
            auth = request.authorization
            if (
                not session.get("authenticated")
                and auth
                and _check_admin_credentials(auth.username, auth.password)
            ):
                return f(*args, **kwargs)

            token_in_header = request.headers.get("X-CSRF-Token")
            token_in_form = request.form.get("csrf_token")
            token_in_session = session.get("csrf_token")

            provided_token = token_in_header or token_in_form
            if (
                not provided_token
                or not token_in_session
                or not secrets.compare_digest(provided_token, token_in_session)
            ):
                logger.warning(
                    f"CSRF validation failed for request from {request.remote_addr}"
                )
                return jsonify({"error": "CSRF validation failed"}), 400
        return f(*args, **kwargs)

    return decorated


def generate_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return str(session["csrf_token"])


app.jinja_env.globals["csrf_token"] = generate_csrf_token


@app.route("/healthz", methods=["GET"])
def healthz() -> tuple[str, int]:
    """Liveness endpoint for container healthchecks."""
    return "OK", 200


def _current_actor() -> str:
    """Resolve the authenticated identity for audit logging."""
    auth = request.authorization
    if auth and _check_admin_credentials(auth.username, auth.password):
        return auth.username or ADMIN_USERNAME
    if session.get("authenticated"):
        return str(session.get("actor", "session_user"))
    return "unknown"


def _finish(result: Dict[str, Any], status: int) -> Any:
    """Return JSON for API clients, or flash + redirect back to the index for browser forms."""
    if _wants_json():
        return jsonify(result), status
    flash(
        result.get("message", "Done"),
        "success" if result.get("success") else "error",
    )
    return redirect(url_for("index"))


@app.route("/login", methods=["GET", "POST"])
def login() -> Any:
    """Session login form for browser access (HTTP Basic auth also remains supported)."""
    if not ADMIN_PASSWORD:
        return abort(
            503, description="Device Manager disabled: Admin password not configured"
        )

    next_url = request.values.get("next") or url_for("index")
    # Only allow same-site relative redirect targets.
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = url_for("index")

    if request.method == "POST":
        if not check_rate_limit():
            return render_template("login.html", error="Rate limit exceeded"), 429

        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if _check_admin_credentials(username, password):
            session.clear()
            session.permanent = True
            session["authenticated"] = True
            session["actor"] = username
            generate_csrf_token()
            logger.info(
                json.dumps(
                    {
                        "event": "login",
                        "actor": username,
                        "result": "success",
                        "remote_addr": request.remote_addr,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )
            return redirect(next_url)

        logger.warning(
            json.dumps(
                {
                    "event": "login",
                    "actor": username or "unknown",
                    "result": "failed",
                    "remote_addr": request.remote_addr,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
        return render_template("login.html", error="Invalid credentials"), 401

    if session.get("authenticated"):
        return redirect(next_url)
    return render_template("login.html", error=None)


@app.route("/logout", methods=["POST"])
@validate_csrf
def logout() -> Any:
    """Terminate the current session."""
    session.clear()
    flash("Logged out", "success")
    return redirect(url_for("login"))


@app.route("/", methods=["GET"])
@require_auth
def index() -> Any:
    """Main page displaying connected and offline devices."""
    client = get_fritz_client()
    devices = client.get_all_hosts()

    online_devices = [d for d in devices if d.get("status")]
    offline_devices = [d for d in devices if not d.get("status")]

    return render_template(
        "index.html",
        online_devices=online_devices,
        offline_devices=offline_devices,
        total_devices=len(devices),
    )


@app.route("/api/devices", methods=["GET"])
@require_auth
def api_devices() -> Any:
    """API endpoint to fetch all devices as JSON."""
    client = get_fritz_client()
    devices = client.get_all_hosts()
    return jsonify(devices)


def _node_type(node: Any) -> str:
    # fritz-avm-client Node.kind ("router"|"repeater"|"powerline"|"unknown").
    return str(getattr(node, "kind", "") or "unknown")


def _build_topology(client: FritzClient) -> Dict[str, Any]:
    """Flatten the typed MeshTopology into the {nodes, links} shape the templates expect."""
    mesh = client.discover_mesh()

    devices_per_node: Dict[str, int] = defaultdict(int)
    for dev in mesh.devices:
        if dev.connected_to:
            devices_per_node[dev.connected_to] += 1

    name_to_mac = {n.name: n.mac for n in mesh.nodes}

    nodes: List[Dict[str, Any]] = []
    for n in mesh.nodes:
        extra = n.extra or {}
        nodes.append(
            {
                "id": n.mac,
                "uid": n.mac,
                "name": n.name,
                "mac": n.mac,
                "ip": n.ip or "",
                "type": _node_type(n),
                "is_router": bool(getattr(n, "is_router", False)),
                "online": bool(extra.get("active", True)),
                "connected_devices": devices_per_node.get(n.name, 0),
                "rx_bytes": int(extra.get("rx_bytes", 0) or 0),
                "tx_bytes": int(extra.get("tx_bytes", 0) or 0),
                "link_rx_kbps": extra.get("link_rx_kbps", 0),
                "link_tx_kbps": extra.get("link_tx_kbps", 0),
            }
        )

    links: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for n in mesh.nodes:
        parent_mac = name_to_mac.get(n.parent_node or "")
        if not parent_mac or parent_mac == n.mac:
            continue
        key = (min(parent_mac, n.mac), max(parent_mac, n.mac))
        if key in seen:
            continue
        seen.add(key)
        links.append({"source": parent_mac, "target": n.mac, "type": "mesh"})

    return {"nodes": nodes, "links": links}


def _render_topology(template: str) -> Any:
    client = get_fritz_client()
    mesh = _build_topology(client)
    devices = client.get_all_hosts()
    online_count = sum(1 for d in devices if d.get("status"))
    return render_template(
        template,
        topology=mesh,
        mesh=mesh,
        devices=devices,
        total_devices=len(devices),
        online_count=online_count,
    )


@app.route("/topology", methods=["GET"])
@require_auth
def topology() -> Any:
    """Network topology card view."""
    return _render_topology("topology.html")


@app.route("/graph", methods=["GET"])
@require_auth
def graph() -> Any:
    """Interactive network graph visualization."""
    return _render_topology("graph.html")


@app.route("/api/topology", methods=["GET"])
@require_auth
def api_topology() -> Any:
    """Mesh topology as JSON."""
    return jsonify(_build_topology(get_fritz_client()))


@app.route("/api/device/delete/<mac>", methods=["POST"])
@require_auth
@validate_csrf
def api_delete_device(mac: str) -> Any:
    """API endpoint to delete a single device by MAC address using client.admin."""
    if not MAC_REGEX.match(mac):
        return _finish({"success": False, "message": "Invalid MAC address format"}, 400)

    actor = _current_actor()
    ref_id = str(uuid.uuid4())[:8]

    try:
        client = get_fritz_client()
        client.admin.delete_host(mac)

        audit_event = {
            "event": "device_delete",
            "actor": actor,
            "target": mac,
            "result": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(json.dumps(audit_event))
        return _finish({"success": True, "message": f"Device {mac} deleted"}, 200)
    except Exception as e:
        audit_event = {
            "event": "device_delete",
            "actor": actor,
            "target": mac,
            "result": "failed",
            "ref_id": ref_id,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.warning(json.dumps(audit_event))
        return _finish(
            {"success": False, "message": f"Deletion failed (Ref: {ref_id})"}, 500
        )


@app.route("/api/devices/delete-offline", methods=["POST"])
@require_auth
@validate_csrf
def api_delete_all_offline() -> Any:
    """API endpoint to delete all offline devices using client.admin."""
    actor = _current_actor()
    ref_id = str(uuid.uuid4())[:8]

    try:
        client = get_fritz_client()
        devices = client.get_all_hosts()
        offline_devices = [
            d
            for d in devices
            if not d.get("status") and MAC_REGEX.match(d.get("mac", ""))
        ]

        deleted = 0
        failed = 0

        for dev in offline_devices:
            mac = dev["mac"]
            try:
                client.admin.delete_host(mac)
                deleted += 1
                audit_event = {
                    "event": "device_delete_offline_single",
                    "actor": actor,
                    "target": mac,
                    "result": "success",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                logger.info(json.dumps(audit_event))
            except Exception as e:
                failed += 1
                audit_event = {
                    "event": "device_delete_offline_single",
                    "actor": actor,
                    "target": mac,
                    "result": "failed",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                logger.warning(json.dumps(audit_event))

        return _finish(
            {
                "success": True,
                "deleted": deleted,
                "failed": failed,
                "message": f"Deleted {deleted} offline devices, {failed} failed",
            },
            200,
        )
    except Exception as e:
        logger.error(f"Bulk offline deletion error (Ref: {ref_id}): {e}")
        return _finish(
            {"success": False, "message": f"Bulk deletion failed (Ref: {ref_id})"}, 500
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
