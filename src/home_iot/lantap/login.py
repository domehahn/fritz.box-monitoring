"""FRITZ!Box web-UI session login (PBKDF2, with legacy MD5 fallback).

TR-064 (fritzconnection) has no session; the packet-capture CGI needs a UI SID.
"""
from __future__ import annotations

import hashlib
import re
import urllib.parse
import urllib.request

_CHALLENGE = re.compile(r"<Challenge>([^<]+)</Challenge>")
_SID = re.compile(r"<SID>([0-9a-fA-F]+)</SID>")
_RIGHTS = re.compile(r"<Rights>(.*?)</Rights>", re.S)


def _response(challenge: str, password: str) -> str:
    if challenge.startswith("2$"):  # PBKDF2 (FRITZ!OS >= 7.24)
        _, i1, s1, i2, s2 = challenge.split("$")
        h1 = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(s1), int(i1)
        )
        h2 = hashlib.pbkdf2_hmac("sha256", h1, bytes.fromhex(s2), int(i2))
        return f"{s2}${h2.hex()}"
    # legacy MD5
    digest = hashlib.md5(f"{challenge}-{password}".encode("utf-16-le")).hexdigest()
    return f"{challenge}-{digest}"


def login(host: str, username: str, password: str, timeout: float = 8.0) -> str:
    """Return a valid SID or raise. ``SID == "0"*16`` means auth failed."""
    base = f"http://{host}/login_sid.lua?version=2"
    xml = urllib.request.urlopen(base, timeout=timeout).read().decode()
    challenge = _CHALLENGE.search(xml).group(1)  # type: ignore[union-attr]
    data = urllib.parse.urlencode(
        {"username": username, "response": _response(challenge, password)}
    ).encode()
    xml2 = urllib.request.urlopen(base, data=data, timeout=timeout).read().decode()
    m = _SID.search(xml2)
    sid = m.group(1) if m else "0" * 16
    if sid == "0" * 16:
        raise PermissionError("FRITZ!Box UI login failed (bad user/password?)")
    rights = _RIGHTS.search(xml2)
    if rights and not rights.group(1).strip():
        raise PermissionError(
            "FRITZ!Box UI login succeeded but the account has no rights — grant "
            "the user the 'FRITZ!Box Einstellungen' permission."
        )
    return sid


def check_session(host: str, sid: str, timeout: float = 6.0) -> bool:
    try:
        xml = (
            urllib.request.urlopen(
                f"http://{host}/login_sid.lua?version=2&sid={sid}", timeout=timeout
            )
            .read()
            .decode()
        )
        m = _SID.search(xml)
        return bool(m and m.group(1) != "0" * 16)
    except Exception:  # noqa: BLE001
        return False
