"""Browser IP as seen through Caddy: public egress, not loopback or LAN."""
from __future__ import annotations

from shared.net import first_public_egress, normalize_ip_text


def _peer_host(request: object) -> str:
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    return normalize_ip_text(str(host or ""))


def _header(request: object, name: str) -> str:
    headers = getattr(request, "headers", None)
    if headers is None:
        return ""
    try:
        return str(headers.get(name) or "")
    except Exception:  # noqa: BLE001
        return ""


def _forwarded_hosts(request: object) -> list[str]:
    out: list[str] = []
    for part in _header(request, "x-forwarded-for").split(","):
        host = normalize_ip_text(part)
        if host:
            out.append(host)
    real = normalize_ip_text(_header(request, "x-real-ip"))
    if real:
        out.append(real)
    return out


def request_client_ip(request: object) -> str:
    """IP to send to the hub as ``client_ip``.

    Caddy proxies to this process on loopback. Trust ``X-Forwarded-For`` /
    ``X-Real-IP`` only then, and keep the first **public** address (the
    caller's router WAN as seen at expenses.apsurt.nl). Direct connections
    use the TCP peer and ignore spoofed forwarded headers.
    """
    peer = _peer_host(request)
    forwarded: list[str] = []
    if peer in ("", "127.0.0.1", "::1"):
        forwarded = _forwarded_hosts(request)
    public = first_public_egress(*forwarded, peer)
    return public or peer or "unknown"
