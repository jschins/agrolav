"""Person login OTP: signed token + Twilio SMS.

No extra SQL table: the code hash lives in a short-lived JWT (``otp_token``).
A non-empty ``dbo.person.mobile_phone`` means this person uses the second step.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from typing import Any

import jwt

OTP_TTL_SEC = 300
OTP_RESEND_SEC = 45
_DEFAULT_OTP_SECRET = "dev-insecure-hub-otp-secret-32b!"

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


def send_sms(phone: str, code: str) -> None:
    """Send the login code via Twilio, or print it when Twilio is not configured."""
    cfg = twilio_config()
    body = f"Your Agrolav login code is {code}. It expires in {OTP_TTL_SEC // 60} minutes."
    if cfg is None:
        print(f"person otp: Twilio unset; code for {mask_phone(phone)} is {code}")
        return
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


def issue_and_send(username: str, phone: str) -> dict[str, Any]:
    """Create a code, SMS it, return ``otp_token`` + ``phone_hint``."""
    name = str(username or "").strip()
    number = str(phone or "").strip()
    if not name or not number:
        raise OtpError("username and mobile phone are required")
    _check_rate(name)
    code = _generate_code()
    send_sms(number, code)
    return {
        "otp_required": True,
        "otp_token": encode_otp_token(name, code),
        "phone_hint": mask_phone(number),
    }
