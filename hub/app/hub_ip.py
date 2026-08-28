"""IP allowlists on ``dbo.hub_ip``.

``target``:
  ``B``              hub :8200 (empty list → unrestricted)
  ``C_{country_id}`` country login on :8300
  ``L_{center_id}``  center login on :8300
  ``P_{person_id}``  person login on :8300

No rows for a login target → that login is IP-unrestricted.
"""
from __future__ import annotations

import re
from typing import Any

from shared.user_access import ACCESS_CENTER, ACCESS_COUNTRY, ACCESS_PERSON

BEHEER_USERNAME = "beheer"
HUB_TARGET = "B"
_TARGET_RE = re.compile(r"^(B|C_[1-9]\d*|L_[1-9]\d*|P_[1-9]\d*)$")
_IPV4_RE = re.compile(
    r"^(?:25[0-5]|2[0-4]\d|[01]?\d\d?)(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)){3}$"
)


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


def validate_target(raw: str | None) -> str:
    target = str(raw or "").strip()
    if not _TARGET_RE.fullmatch(target):
        raise HubIpError(f"Invalid target: {target}")
    return target


def is_beheer(username: str | None) -> bool:
    return str(username or "").strip().casefold() == BEHEER_USERNAME


def _has_target_column(cursor) -> bool:
    cursor.execute("SELECT COL_LENGTH(N'dbo.hub_ip', N'target')")
    row = cursor.fetchone()
    return bool(row and row[0])


def _cursor():
    from app import user_store

    if not user_store.database_url():
        return None
    user_store.init_user_store()
    return user_store._sql_connect().cursor()


def hub_b_ips() -> frozenset[str]:
    """IPs allowed on :8200. Empty means no hub-wide gate."""
    cursor = _cursor()
    if cursor is None:
        return frozenset()
    try:
        if not _has_target_column(cursor):
            return frozenset()
        cursor.execute("SELECT ip FROM dbo.hub_ip WHERE target = ?", (HUB_TARGET,))
        return frozenset(normalize_ip(str(row[0])) for row in cursor.fetchall() if row[0])
    except Exception:
        return frozenset()


def ips_for_target(target: str) -> frozenset[str]:
    cursor = _cursor()
    if cursor is None:
        return frozenset()
    if not _has_target_column(cursor):
        return frozenset()
    cursor.execute(
        "SELECT ip FROM dbo.hub_ip WHERE target = ?",
        (validate_target(target),),
    )
    return frozenset(normalize_ip(str(row[0])) for row in cursor.fetchall() if row[0])


def target_for_user(user: dict[str, Any]) -> str | None:
    from app.user_store import _public_user

    rec = _public_user(dict(user))
    ident = int(user.get("id") or rec.get("id") or 0)
    if ident <= 0:
        return None
    access = str(rec.get("access") or "").strip().lower()
    if access == ACCESS_PERSON:
        return f"P_{ident}"
    if access == ACCESS_CENTER:
        return f"L_{ident}"
    if access == ACCESS_COUNTRY:
        return f"C_{ident}"
    return None


def login_ip_allowed(user: dict[str, Any], client_ip: str | None) -> bool:
    target = target_for_user(user)
    if not target:
        return True
    allowed = ips_for_target(target)
    if not allowed:
        return True
    ip = normalize_ip(client_ip)
    return bool(ip) and ip in allowed


def _user_by_username(username: str) -> dict[str, Any]:
    from app import user_store

    user = user_store.find_user(username)
    if user is None:
        raise HubIpError("unknown user")
    return user


def _label_for_target(cursor, target: str) -> dict[str, str]:
    if target == HUB_TARGET:
        return {"target": target, "kind": "hub", "label": "Hub 8200", "username": ""}
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
    if kind == "L":
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
    cursor.execute(
        "SELECT username, title FROM dbo.person WHERE id = ?",
        (ident,),
    )
    row = cursor.fetchone()
    name = str(row[0] if row else ident)
    title = str(row[1] if row else "")
    return {
        "target": target,
        "kind": "person",
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
        out.append(_label_for_target(cursor, HUB_TARGET))
        cursor.execute("SELECT country_id FROM dbo.country ORDER BY username")
        for (cid,) in cursor.fetchall():
            out.append(_label_for_target(cursor, f"C_{int(cid)}"))
        cursor.execute("SELECT center_id FROM dbo.center ORDER BY username")
        for (cid,) in cursor.fetchall():
            out.append(_label_for_target(cursor, f"L_{int(cid)}"))
        cursor.execute("SELECT id FROM dbo.person ORDER BY username")
        for (pid,) in cursor.fetchall():
            out.append(_label_for_target(cursor, f"P_{int(pid)}"))
        return out

    if access == ACCESS_PERSON and ident:
        return [_label_for_target(cursor, f"P_{ident}")]

    if access == ACCESS_CENTER and ident:
        out.append(_label_for_target(cursor, f"L_{ident}"))
        cursor.execute(
            "SELECT id FROM dbo.person WHERE center_id = ? ORDER BY username",
            (ident,),
        )
        for (pid,) in cursor.fetchall():
            out.append(_label_for_target(cursor, f"P_{int(pid)}"))
        return out

    if access == ACCESS_COUNTRY and ident:
        out.append(_label_for_target(cursor, f"C_{ident}"))
        cursor.execute(
            "SELECT center_id FROM dbo.center WHERE country_id = ? ORDER BY username",
            (ident,),
        )
        for (cid,) in cursor.fetchall():
            out.append(_label_for_target(cursor, f"L_{int(cid)}"))
        cursor.execute(
            "SELECT id FROM dbo.person WHERE country_id = ? ORDER BY username",
            (ident,),
        )
        for (pid,) in cursor.fetchall():
            out.append(_label_for_target(cursor, f"P_{int(pid)}"))
        return out

    return out


def _assert_can_edit(username: str, target: str) -> None:
    wanted = validate_target(target)
    allowed = {item["target"] for item in editable_targets(username)}
    if wanted not in allowed:
        raise HubIpError("You cannot edit IP access for that login")


def list_access(username: str) -> dict[str, Any]:
    targets = editable_targets(username)
    allowed = {item["target"] for item in targets}
    cursor = _cursor()
    if cursor is None:
        raise HubIpError("SQL Server is not configured")
    rows: list[dict[str, str]] = []
    if allowed and _has_target_column(cursor):
        labels = {item["target"]: item for item in targets}
        placeholders = ",".join("?" for _ in allowed)
        cursor.execute(
            f"SELECT ip, target FROM dbo.hub_ip WHERE target IN ({placeholders}) ORDER BY target, ip",
            tuple(sorted(allowed)),
        )
        for ip, target in cursor.fetchall():
            meta = labels.get(str(target) or "") or {
                "target": str(target or ""),
                "kind": "",
                "label": str(target or ""),
                "username": "",
            }
            rows.append(
                {
                    "ip": normalize_ip(str(ip or "")),
                    "target": str(target or ""),
                    "kind": meta.get("kind") or "",
                    "label": meta.get("label") or str(target or ""),
                    "username": meta.get("username") or "",
                }
            )
    return {
        "can_edit_b": is_beheer(username),
        "targets": targets,
        "rows": rows,
    }


def add_ip(username: str, *, ip: str, target: str) -> dict[str, Any]:
    cursor = _cursor()
    if cursor is None:
        raise HubIpError("SQL Server is not configured")
    if not _has_target_column(cursor):
        raise HubIpError("dbo.hub_ip.target is missing")
    ip_s = validate_ip(ip)
    target_s = validate_target(target)
    _assert_can_edit(username, target_s)
    cursor.execute(
        "SELECT 1 FROM dbo.hub_ip WHERE ip = ? AND target = ?",
        (ip_s, target_s),
    )
    if cursor.fetchone():
        raise HubIpError(f"IP {ip_s} is already registered for that login")
    cursor.execute(
        "INSERT INTO dbo.hub_ip (ip, target) VALUES (?, ?)",
        (ip_s[:64], target_s),
    )
    from app import user_store

    user_store._sql_connect().commit()
    return list_access(username)


def delete_ip(username: str, *, ip: str, target: str) -> dict[str, Any]:
    cursor = _cursor()
    if cursor is None:
        raise HubIpError("SQL Server is not configured")
    if not _has_target_column(cursor):
        raise HubIpError("dbo.hub_ip.target is missing")
    ip_s = validate_ip(ip)
    target_s = validate_target(target)
    _assert_can_edit(username, target_s)
    cursor.execute(
        "DELETE FROM dbo.hub_ip WHERE ip = ? AND target = ?",
        (ip_s, target_s),
    )
    if cursor.rowcount == 0:
        raise HubIpError("That IP is not registered for that login")
    from app import user_store

    user_store._sql_connect().commit()
    return list_access(username)
