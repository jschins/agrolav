"""Public (egress) IP helpers. LAN / loopback addresses are not recorded."""
from __future__ import annotations

import ipaddress


def normalize_ip_text(raw: str | None) -> str:
    text = (raw or "").strip().strip("[]")
    if text.lower() in ("unknown",):
        return ""
    if text.startswith("::ffff:"):
        text = text.split("::ffff:", 1)[-1]
    if text.count(":") == 1 and "." in text:
        host, _, port = text.rpartition(":")
        if port.isdigit():
            text = host
    return text.strip()


def is_public_egress_ip(raw: str | None) -> bool:
    """True for a globally routable unicast address (home router WAN, not LAN)."""
    text = normalize_ip_text(raw)
    if not text:
        return False
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return False
    return not (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def first_public_egress(*candidates: str | None) -> str:
    for raw in candidates:
        text = normalize_ip_text(raw)
        if is_public_egress_ip(text):
            return text
    return ""
