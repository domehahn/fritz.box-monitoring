#!/usr/bin/env python3
"""
Fritz!Box Device Management Web Interface (Secured)
Provides authenticated device viewing, topology representation, and hardened deletion operations.
"""
from __future__ import annotations
import os
import re
import json
import secrets
from datetime import datetime, timezone
from functools import wraps
from typing import Callable, Any
from flask import Flask, render_template, request, jsonify, session, abort, Response
from loguru import logger

from fritz_avm_client import FritzClient, Settings as FritzSettings
from ..config import Settings

app = Flask(__name__)


def resolve_secret_key() -> str:
    """Resolve Flask secret key from file or environment."""
    secret_key_file = os.getenv('DEVICE_MANAGER_SECRET_KEY_FILE')
    if secret_key_file and os.path.exists(secret_key_file):
        try:
            with open(secret_key_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception as exc:
            logger.warning(f"Failed to read DEVICE_MANAGER_SECRET_KEY_FILE: {exc}")
    return os.getenv('SECRET_KEY', secrets.token_hex(32))


app.config['SECRET_KEY'] = resolve_secret_key()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

settings = Settings()
ADMIN_PASSWORD = settings.resolved_device_manager_admin_password

MAC_REGEX = re.compile(r'^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$')


@app.after_request
def apply_security_headers(response: Response) -> Response:
    """Attach HTTP security headers to all responses."""
    response.headers['Content-Security-Policy'] = "default-src 'self'"
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
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


def require_auth(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator enforcing authentication when ADMIN_PASSWORD is set or failing fast if not set."""
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if not ADMIN_PASSWORD:
            logger.error("Device Manager accessed but DEVICE_MANAGER_ADMIN_PASSWORD(_FILE) is not configured")
            return abort(503, description="Device Manager disabled: Admin password not configured")

        auth = request.authorization
        if auth and auth.password == ADMIN_PASSWORD:
            return f(*args, **kwargs)

        if session.get('authenticated'):
            return f(*args, **kwargs)

        return (
            jsonify({'error': 'Unauthorized: Admin authentication required'}),
            401,
            {'WWW-Authenticate': 'Basic realm="Fritz Device Manager"'}
        )
    return decorated


def validate_csrf(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator validating CSRF token for state-changing POST requests."""
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if request.method == 'POST':
            token_in_header = request.headers.get('X-CSRF-Token')
            token_in_form = request.form.get('csrf_token')
            token_in_session = session.get('csrf_token')

            provided_token = token_in_header or token_in_form
            if not provided_token or not token_in_session or not secrets.compare_digest(provided_token, token_in_session):
                logger.warning(f"CSRF validation failed for request from {request.remote_addr}")
                return jsonify({'error': 'CSRF validation failed'}), 400
        return f(*args, **kwargs)
    return decorated


def generate_csrf_token() -> str:
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(16)
    return str(session['csrf_token'])


app.jinja_env.globals['csrf_token'] = generate_csrf_token


@app.route('/healthz', methods=['GET'])
def healthz() -> tuple[str, int]:
    """Liveness endpoint for container healthchecks."""
    return 'OK', 200


@app.route('/', methods=['GET'])
@require_auth
def index() -> Any:
    """Main page displaying connected and offline devices."""
    client = get_fritz_client()
    devices = client.get_all_hosts()

    online_devices = [d for d in devices if d.get('status')]
    offline_devices = [d for d in devices if not d.get('status')]

    return render_template(
        'index.html',
        online_devices=online_devices,
        offline_devices=offline_devices,
        total_devices=len(devices),
    )


@app.route('/api/devices', methods=['GET'])
@require_auth
def api_devices() -> Any:
    """API endpoint to fetch all devices as JSON."""
    client = get_fritz_client()
    devices = client.get_all_hosts()
    return jsonify(devices)


@app.route('/api/device/delete/<mac>', methods=['POST'])
@require_auth
@validate_csrf
def api_delete_device(mac: str) -> Any:
    """API endpoint to delete a single device by MAC address."""
    if not MAC_REGEX.match(mac):
        return jsonify({'success': False, 'message': 'Invalid MAC address format'}), 400

    actor = request.authorization.username if request.authorization else "session_user"
    try:
        client = get_fritz_client()
        result = client.fc.call_action(
            'Hosts1',
            'X_AVM-DE_DeleteHostEntry',
            NewMACAddress=mac
        )
        audit_event = {
            "event": "device_delete",
            "actor": actor,
            "target": mac,
            "result": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(json.dumps(audit_event))
        return jsonify({'success': True, 'message': f'Device {mac} deleted', 'result': result})
    except Exception as e:
        audit_event = {
            "event": "device_delete",
            "actor": actor,
            "target": mac,
            "result": "failed",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.warning(json.dumps(audit_event))
        return jsonify({'success': False, 'message': f'Deletion failed: {e}'}), 500


@app.route('/api/devices/delete-offline', methods=['POST'])
@require_auth
@validate_csrf
def api_delete_all_offline() -> Any:
    """API endpoint to delete all offline devices."""
    actor = request.authorization.username if request.authorization else "session_user"
    try:
        client = get_fritz_client()
        devices = client.get_all_hosts()
        offline_devices = [d for d in devices if not d.get('status') and MAC_REGEX.match(d.get('mac', ''))]

        deleted = 0
        failed = 0

        for dev in offline_devices:
            mac = dev['mac']
            try:
                client.fc.call_action('Hosts1', 'X_AVM-DE_DeleteHostEntry', NewMACAddress=mac)
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

        return jsonify({
            'success': True,
            'deleted': deleted,
            'failed': failed,
            'message': f'Deleted {deleted} offline devices, {failed} failed',
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
