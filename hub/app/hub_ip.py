"""Country/center login allowlists on ``egress_ip``, plus ``dbo.visitor_ip`` logs.

Country and center logins (one-step) are allowed from IPs listed in
``dbo.administrator`` or in their own ``dbo.country.egress_ip`` /
``dbo.center.egress_ip`` column (comma-separated). The allowed set is the sum
of those two tables; an empty or NULL column admits nothing, so a database
with no addresses listed anywhere refuses every country and center login.
Person logins are not IP-gated.

``dbo.visitor_ip`` records attempted client IPs. Successful login stores the
username; a refused attempt stores ``''`` (not NULL) so
``UNIQUE (egress_ip, username)`` collapses repeats from the same IP. Addresses
listed in ``dbo.administrator`` are not logged; every other visitor is, whether
or not a country or center lists it.
"""
from __future__ import annotations

import re
from typing import Any

from shared.net import is_public_egress_ip
from shared.user_access import ACCESS_CENTER, ACCESS_COUNTRY, ACCESS_PERSON

BEHEER_USERNAME = "beheer"
_IPV4_RE = re.compile(
    r"^(?:25[0-5]|2[0-4]\d|[01]?\d\d?)(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)){3}$"
)
_TARGET_RE = re.compile(r"^(C_[1-9]\d*|L_[1-9]\d*)$")


class HubIpError(ValueError):
    pass


def normalize_ip(raw: str | None) -> str:
    from app.upload_acl import _normalize_ip

    return _normalize_ip(raw or "")


def validate_ip(raw: str | None) -> str:
    ip = normalize_ip(raw)
    if not ip or ip == "unknown" or "x" in ip.lower():
        raise HubIpError("IP address is required")
    if _IPV4_RE.fullmatch(ip):
        return ip
    if ":" in ip:
        return ip
    raise HubIpError(f"Invalid IP address: {ip}")


def parse_egress_list(raw: str | None) -> list[str]:
    """Split a comma-separated ``egress_ip`` column into normalized IPs."""
    out: list[str] = []
    seen: set[str] = set()
    for part in str(raw or "").split(","):
        ip = normalize_ip(part)
        if not ip or ip in seen:
            continue
        seen.add(ip)
        out.append(ip)
    return out


def format_egress_list(ips: list[str]) -> str | None:
    cleaned = parse_egress_list(",".join(ips))
    text = ",".join(cleaned)
    if len(text) > 256:
        raise HubIpError("Too many IP addresses for the egress_ip column (max 256 characters)")
    return text or None


def ip_in_allowlist(client_ip: str | None, allow: list[str]) -> bool:
    """Membership test. An empty allowlist admits nothing."""
    ip = normalize_ip(client_ip)
    return bool(ip) and ip in allow


def is_beheer(username: str | None) -> bool:
    return str(username or "").strip().casefold() == BEHEER_USERNAME


def _cursor():
    from app import user_store

    if not user_store.database_url():
        return None
    user_store.init_user_store()
    return user_store._sql_connect().cursor()


def _has_egress_column(cursor, table: str) -> bool:
    cursor.execute(f"SELECT COL_LENGTH(N'dbo.{table}', N'egress_ip')")
    row = cursor.fetchone()
    return bool(row and row[0])


def _has_visitor_table(cursor) -> bool:
    cursor.execute("SELECT OBJECT_ID(N'dbo.visitor_ip', N'U')")
    row = cursor.fetchone()
    return bool(row and row[0])


def administrator_ip_allowed(client_ip: str | None) -> bool:
    """Whether ``client_ip`` occurs in ``dbo.administrator``.

    A missing table means no administrator bypass, allowing the code to be
    deployed before the database migration.
    """
    ip = normalize_ip(client_ip)
    if not ip:
        return False
    cursor = _cursor()
    if cursor is None:
        return False
    cursor.execute("SELECT OBJECT_ID(N'dbo.administrator', N'U')")
    row = cursor.fetchone()
    if not row or not row[0]:
        return False
    cursor.execute(
        """
        SELECT TOP 1 1
        FROM dbo.administrator
        WHERE egress_ip = ?
        """,
        (ip,),
    )
    return cursor.fetchone() is not None


def hub_b_ips() -> frozenset[str]:
    """Hub :8200 allowlist is no longer stored in SQL. Empty → unrestricted."""
    return frozenset()


def _egress_raw_for_user(user: dict[str, Any]) -> str | None:
    """This login's own comma-separated allowlist, or ``None`` if it has none.

    ``None`` covers a NULL column, a missing row and a missing ``egress_ip``
    column alike: none of them list an address, so none of them admit one.
    """
    ident = int(user.get("id") or 0)
    if ident <= 0 or str(user.get("person") or "").strip():
        return None
    cursor = _cursor()
    if cursor is None:
        return None
    center = str(user.get("center") or "").strip()
    country = str(user.get("country") or "").strip()
    table = "center" if center else "country" if country else ""
    if not table:
        return None
    if not _has_egress_column(cursor, table):
        print(
            f"egress_ip: dbo.{table}.egress_ip is missing — run "
            f"hub/sql/visitor_ip.sql; no {table} login can be allowed"
        )
        return None
    key = "center_id" if table == "center" else "country_id"
    cursor.execute(
        f"SELECT egress_ip FROM dbo.{table} WHERE {key} = ?",
        (ident,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return None if row[0] is None else str(row[0])


def login_ip_allowed(user: dict[str, Any], client_ip: str | None) -> bool:
    """Whether this login may proceed from ``client_ip``.

    A country or center login needs its address listed in
    ``dbo.administrator`` or in its own ``egress_ip`` column; the allowed set
    is the sum of the two. An address listed in neither is refused, so no
    listed address anywhere means no such login at all. Person logins carry
    their own password (and optional OTP) and stay ungated.
    """
    if str(user.get("person") or "").strip():
        return True
    ip = normalize_ip(client_ip)
    if not ip or ip == "unknown":
        return False
    try:
        if administrator_ip_allowed(ip):
            return True
    except Exception as exc:  # noqa: BLE001
        # Falling through to the login's own list is never more permissive
        # than the sum of both, so a failed lookup here cannot open a door.
        print(f"administrator: could not check egress IP {ip!r}: {exc}")
    try:
        raw = _egress_raw_for_user(user)
    except Exception as exc:  # noqa: BLE001
        print(f"egress_ip: could not read the allowlist for {ip!r}: {exc}")
        return False
    return ip_in_allowlist(ip, parse_egress_list(raw))


def record_visit(client_ip: str | None, username: str | None = None) -> None:
    """Insert ``dbo.visitor_ip`` if this (ip, username) pair is new.

    Refused login uses ``username = ''`` so ``UNIQUE (egress_ip, username)``
    blocks a second row for the same IP. Only a public address is stored
    (the router WAN as seen by Caddy), never loopback or LAN. An address in
    ``dbo.administrator`` is ours and is skipped; anything else is logged,
    whether or not a country or center lists it.
    """
    ip_s = normalize_ip(client_ip)
    if not is_public_egress_ip(ip_s):
        return
    try:
        if administrator_ip_allowed(ip_s):
            return
    except Exception as exc:  # noqa: BLE001
        # Rather log one of our own addresses than lose a real visitor.
        print(f"visitor_ip: could not read dbo.administrator for {ip_s!r}: {exc}")
    ip_s = ip_s[:32]
    name = str(username or "").strip()[:64]
    cursor = _cursor()
    if cursor is None or not _has_visitor_table(cursor):
        return
    try:
        cursor.execute(
            """
            SELECT TOP 1 visitor_id FROM dbo.visitor_ip
            WHERE egress_ip = ? AND ISNULL(username, '') = ?
            """,
            (ip_s, name),
        )
        if cursor.fetchone():
            return
        cursor.execute(
            "INSERT INTO dbo.visitor_ip (egress_ip, username) VALUES (?, ?)",
            (ip_s, name),
        )
        from app import user_store

        user_store._sql_connect().commit()
    except Exception as exc:  # noqa: BLE001
        print(f"visitor_ip: failed to record {ip_s!r}: {exc}")


def validate_target(raw: str | None) -> str:
    target = str(raw or "").strip()
    if not _TARGET_RE.fullmatch(target):
        raise HubIpError(f"Invalid target: {target}")
    return target


def _user_by_username(username: str) -> dict[str, Any]:
    from app import user_store

    user = user_store.find_user(username)
    if user is None:
        raise HubIpError("unknown user")
    return user


def _label_for_target(cursor, target: str) -> dict[str, str]:
    kind, _, ident_s = target.partition("_")
    ident = int(ident_s)
    if kind == "C":
        cursor.execute(
            "SELECT username, title FROM dbo.country WHERE country_id = ?",
            (ident,),
        )
        row = cursor.fetchone()
        name = str(row[0] if row else ident)
        title = str(row[1] if row else "")
        return {
            "target": target,
            "kind": "country",
            "label": title.strip() or name,
            "username": name,
        }
    cursor.execute(
        "SELECT username, title FROM dbo.center WHERE center_id = ?",
        (ident,),
    )
    row = cursor.fetchone()
    name = str(row[0] if row else ident)
    title = str(row[1] if row else "")
    return {
        "target": target,
        "kind": "center",
        "label": title.strip() or name,
        "username": name,
    }


def editable_targets(username: str) -> list[dict[str, str]]:
    cursor = _cursor()
    if cursor is None:
        raise HubIpError("SQL Server is not configured")
    user = _user_by_username(username)
    from app.user_store import _public_user

    rec = _public_user(dict(user))
    ident = int(user.get("id") or 0)
    access = str(rec.get("access") or "").strip().lower()
    out: list[dict[str, str]] = []

    if is_beheer(username):
        cursor.execute("SELECT country_id FROM dbo.country ORDER BY username")
        for (cid,) in cursor.fetchall():
            out.append(_label_for_target(cursor, f"C_{int(cid)}"))
        cursor.execute("SELECT center_id FROM dbo.center ORDER BY username")
        for (cid,) in cursor.fetchall():
            out.append(_label_for_target(cursor, f"L_{int(cid)}"))
        return out

    if access == ACCESS_CENTER and ident:
        return [_label_for_target(cursor, f"L_{ident}")]

    if access == ACCESS_COUNTRY and ident:
        out.append(_label_for_target(cursor, f"C_{ident}"))
        cursor.execute(
            "SELECT center_id FROM dbo.center WHERE country_id = ? ORDER BY username",
            (ident,),
        )
        for (cid,) in cursor.fetchall():
            out.append(_label_for_target(cursor, f"L_{int(cid)}"))
        return out

    return out


def _assert_can_edit(username: str, target: str) -> None:
    wanted = validate_target(target)
    allowed = {item["target"] for item in editable_targets(username)}
    if wanted not in allowed:
        raise HubIpError("You cannot edit IP access for that login")


def _read_target_ips(cursor, target: str) -> list[str]:
    kind, _, ident_s = target.partition("_")
    ident = int(ident_s)
    table = "country" if kind == "C" else "center"
    key = "country_id" if kind == "C" else "center_id"
    if not _has_egress_column(cursor, table):
        raise HubIpError("dbo.country/center.egress_ip is missing — run hub/sql/visitor_ip.sql")
    cursor.execute(f"SELECT egress_ip FROM dbo.{table} WHERE {key} = ?", (ident,))
    row = cursor.fetchone()
    return parse_egress_list(None if not row else row[0])


def _write_target_ips(cursor, target: str, ips: list[str]) -> None:
    kind, _, ident_s = target.partition("_")
    ident = int(ident_s)
    table = "country" if kind == "C" else "center"
    key = "country_id" if kind == "C" else "center_id"
    text = format_egress_list(ips)
    cursor.execute(
        f"UPDATE dbo.{table} SET egress_ip = ? WHERE {key} = ?",
        (text, ident),
    )


def list_access(username: str) -> dict[str, Any]:
    targets = editable_targets(username)
    cursor = _cursor()
    if cursor is None:
        raise HubIpError("SQL Server is not configured")
    rows: list[dict[str, str]] = []
    for meta in targets:
        target = meta["target"]
        try:
            ips = _read_target_ips(cursor, target)
        except HubIpError:
            ips = []
        for ip in ips:
            rows.append(
                {
                    "ip": ip,
                    "target": target,
                    "kind": meta.get("kind") or "",
                    "label": meta.get("label") or target,
                    "username": meta.get("username") or "",
                }
            )
    return {
        "can_edit_b": False,
        "targets": targets,
        "rows": rows,
    }


def add_ip(username: str, *, ip: str, target: str) -> dict[str, Any]:
    cursor = _cursor()
    if cursor is None:
        raise HubIpError("SQL Server is not configured")
    ip_s = validate_ip(ip)
    target_s = validate_target(target)
    _assert_can_edit(username, target_s)
    ips = _read_target_ips(cursor, target_s)
    if ip_s in ips:
        raise HubIpError(f"IP {ip_s} is already registered for that login")
    ips.append(ip_s)
    _write_target_ips(cursor, target_s, ips)
    from app import user_store

    user_store._sql_connect().commit()
    return list_access(username)


def delete_ip(username: str, *, ip: str, target: str) -> dict[str, Any]:
    cursor = _cursor()
    if cursor is None:
        raise HubIpError("SQL Server is not configured")
    ip_s = validate_ip(ip)
    target_s = validate_target(target)
    _assert_can_edit(username, target_s)
    ips = _read_target_ips(cursor, target_s)
    if ip_s not in ips:
        raise HubIpError("That IP is not registered for that login")
    _write_target_ips(cursor, target_s, [item for item in ips if item != ip_s])
    from app import user_store

    user_store._sql_connect().commit()
    return list_access(username)
