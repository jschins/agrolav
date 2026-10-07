"""Login second step: authenticator TOTP, plus the old Twilio sender.

The live login path checks a stored ``totp_secret``. Twilio is unused there.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from typing import Any
from urllib.parse import quote

import jwt

OTP_TTL_SEC = 300
OTP_RESEND_SEC = 45
ENROLL_TTL_SEC = 600
TOTP_STEP_SEC = 30
_DEFAULT_OTP_SECRET = "dev-insecure-hub-otp-secret-32b!"
_log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_last_send: dict[str, float] = {}


class OtpError(ValueError):
    """User-facing OTP / SMS failure."""

    def __init__(self, message: str, *, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def otp_secret() -> str:
    return os.environ.get("HUB_OTP_SECRET", "").strip() or _DEFAULT_OTP_SECRET


def twilio_config() -> tuple[str, str, str] | None:
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    sender = os.environ.get("TWILIO_FROM", "").strip()
    if sid and token and sender:
        return sid, token, sender
    return None


def mask_phone(phone: str) -> str:
    digits = str(phone or "").strip()
    if len(digits) <= 6:
        return "••••"
    return f"{digits[:4]}{'•' * max(3, len(digits) - 7)}{digits[-3:]}"


def _digest(username: str, code: str) -> str:
    raw = f"{otp_secret()}:{username}:{code}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def encode_otp_token(username: str, code: str, *, now: int | None = None) -> str:
    issued = int(now if now is not None else time.time())
    payload = {
        "u": str(username).strip(),
        "ch": _digest(username, code),
        "exp": issued + OTP_TTL_SEC,
    }
    return jwt.encode(payload, otp_secret(), algorithm="HS256")


def username_from_otp_token(token: str) -> str | None:
    try:
        payload = jwt.decode(str(token or ""), otp_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    name = str(payload.get("u") or "").strip()
    return name or None


def verify_otp_token(token: str, code: str) -> str | None:
    """Return the username if ``code`` matches the token, else ``None``."""
    try:
        payload = jwt.decode(str(token or ""), otp_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    username = str(payload.get("u") or "").strip()
    stored = str(payload.get("ch") or "")
    if not username or not stored:
        return None
    got = _digest(username, str(code or "").strip())
    if not hmac.compare_digest(stored, got):
        return None
    return username


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _check_rate(username: str) -> None:
    name = str(username or "").strip().lower()
    now = time.time()
    with _LOCK:
        last = _last_send.get(name, 0.0)
        if now - last < OTP_RESEND_SEC:
            wait = int(OTP_RESEND_SEC - (now - last)) + 1
            raise OtpError(f"Wait {wait}s before requesting another code", status=429)
        _last_send[name] = now


def send_sms(phone: str, code: str) -> bool:
    """Send the login code via Twilio.

    Returns ``True`` when Twilio accepted the message. Returns ``False`` when
    Twilio is not configured (the code is logged for local testing).
    """
    cfg = twilio_config()
    body = f"Your Agrolav login code is {code}. It expires in {OTP_TTL_SEC // 60} minutes."
    if cfg is None:
        _log.warning("person otp: Twilio unset; code for %s is %s", mask_phone(phone), code)
        print(f"person otp: Twilio unset; code for {mask_phone(phone)} is {code}", flush=True)
        return False
    sid, token, sender = cfg
    try:
        import requests
    except ImportError as exc:  # pragma: no cover
        raise OtpError("requests is required to send SMS") from exc
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    try:
        response = requests.post(
            url,
            auth=(sid, token),
            data={"From": sender, "To": phone, "Body": body},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise OtpError(f"Could not send SMS ({exc})") from exc
    if response.status_code >= 300:
        detail = (response.text or response.reason)[:300]
        raise OtpError(f"Twilio rejected the SMS ({response.status_code}): {detail}")
    return True


def issue_and_send(username: str, phone: str) -> dict[str, Any]:
    """Create a code, SMS it, return ``otp_token`` + ``phone_hint``."""
    name = str(username or "").strip()
    number = str(phone or "").strip()
    if not name or not number:
        raise OtpError("username and mobile phone are required")
    _check_rate(name)
    code = _generate_code()
    sent = send_sms(number, code)
    payload: dict[str, Any] = {
        "otp_required": True,
        "otp_token": encode_otp_token(name, code),
        "phone_hint": mask_phone(number),
    }
    if not sent:
        payload["dev_code"] = code
    return payload


def generate_totp_secret() -> str:
    """160-bit base32 secret, no padding. This is the enrollment key."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def secret_groups(secret: str) -> str:
    """Four-character groups for typing the secret by hand."""
    compact = "".join(str(secret or "").split()).upper()
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))


def otpauth_uri(username: str, secret: str) -> str:
    """``otpauth://totp/Agrolav:<username>?secret=...&issuer=Agrolav``."""
    name = str(username or "").strip()
    key = "".join(str(secret or "").split()).upper()
    label = "Agrolav:" + quote(name, safe="")
    return f"otpauth://totp/{label}?secret={key}&issuer=Agrolav"


def qr_data_uri(text: str) -> str:
    """SVG data URI for an authenticator app to scan."""
    import segno

    return segno.make(str(text or ""), error="m").svg_data_uri(scale=4)


def _b32decode(secret: str) -> bytes:
    compact = "".join(str(secret or "").split()).upper().rstrip("=")
    if not compact or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for ch in compact):
        raise OtpError("Authenticator secret is not valid", status=400)
    pad = "=" * ((8 - len(compact) % 8) % 8)
    return base64.b32decode(compact + pad, casefold=True)


def hotp(key: bytes, counter: int) -> str:
    """Six-digit HOTP (RFC 4226) with SHA-1."""
    digest = hmac.new(key, int(counter).to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{binary % 1_000_000:06d}"


def totp_matches(secret: str, code: str, *, now: int | None = None, window: int = 1) -> bool:
    """True when ``code`` matches the secret at ``now``, plus or minus ``window`` steps."""
    digits = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(digits) != 6:
        return False
    try:
        key = _b32decode(secret)
    except (OtpError, ValueError):
        return False
    moment = int(now if now is not None else time.time())
    step = moment // TOTP_STEP_SEC
    for delta in range(-int(window), int(window) + 1):
        if hmac.compare_digest(hotp(key, step + delta), digits):
            return True
    return False


def encode_login_token(username: str, *, now: int | None = None) -> str:
    """Short-lived JWT that names the username. The code is not inside it."""
    issued = int(now if now is not None else time.time())
    payload = {"u": str(username).strip(), "p": "login", "exp": issued + OTP_TTL_SEC}
    return jwt.encode(payload, otp_secret(), algorithm="HS256")


def username_from_login_token(token: str) -> str | None:
    try:
        payload = jwt.decode(str(token or ""), otp_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if str(payload.get("p") or "") != "login":
        return None
    name = str(payload.get("u") or "").strip()
    return name or None


def encode_enroll_token(username: str, secret: str, *, now: int | None = None) -> str:
    """Signed pending secret. It is not written to SQL until the first code matches."""
    issued = int(now if now is not None else time.time())
    payload = {
        "u": str(username).strip(),
        "p": "enroll",
        "s": "".join(str(secret or "").split()).upper(),
        "exp": issued + ENROLL_TTL_SEC,
    }
    return jwt.encode(payload, otp_secret(), algorithm="HS256")


def enroll_from_token(token: str) -> tuple[str, str] | None:
    try:
        payload = jwt.decode(str(token or ""), otp_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if str(payload.get("p") or "") != "enroll":
        return None
    name = str(payload.get("u") or "").strip()
    secret = str(payload.get("s") or "").strip()
    if not name or not secret:
        return None
    return name, secret
