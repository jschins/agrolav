"""Hand journal and automatic-journal rules for the client menu.

The client on port 8300 calls these through the hub.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def resolve_country_id(center: str, country: str | None) -> int:
    from app.runtime import request_country
    from app.sql_catalog import country_username_for_scope
    from app import user_store

    key = (country or "").strip() or str(request_country() or "").strip()
    if not key:
        key = country_username_for_scope(center) or ""
    if not key:
        raise ValueError("country is required")
    cursor = user_store._sql_connect().cursor()
    country_id = user_store._sql_country_id(cursor, key)
    if country_id is None:
        raise ValueError(f"Unknown country {key}")
    return int(country_id)


def _cursor():
    from app import user_store

    return user_store._sql_connect().cursor()


def _connection():
    from app import user_store

    return user_store._sql_connect()


def journal_payload(country_id: int, year: int) -> dict[str, Any]:
    cats = list_journal_categories(country_id)
    return {
        "year": int(year),
        "categories": cats.get("categories") or [],
        "remainder_id": cats.get("remainder_id"),
        "rows": list_journal(country_id, int(year)),
    }


def list_journal_categories(country_id: int) -> dict[str, Any]:
    """Journal-eligible categories, plus the remainder id used as the default."""
    from shared.balance_values import (
        category_labels,
        category_local_codes,
        category_map,
        category_roles,
        ensure_category_role_booking_rules,
        infer_side,
        is_journal_forbidden_code,
        require_remainder_row,
    )

    cur = _cursor()
    ensure_category_role_booking_rules(cur)
    labels = category_labels(country_id, cur)
    roles = category_roles(country_id, cur)
    mapped = category_map(country_id, cur)
    remainder_id, _remainder_code = require_remainder_row(country_id, cur)
    local_codes = category_local_codes(country_id, cur)
    cur.execute(
        "SELECT DISTINCT category_id FROM dbo.dim_category "
        "WHERE country_id = ? AND local_code BETWEEN 1000 AND 4999",
        int(country_id),
    )
    ids = {int(row[0]) for row in cur.fetchall()}
    ids.add(int(remainder_id))
    account_ids = {
        int(account_id)
        for _cat, (_side, account_id) in mapped.items()
        if account_id is not None
    }
    balances: dict[int, Decimal] = {}
    ibans: dict[int, str] = {}
    if account_ids:
        marks = ",".join("?" for _ in account_ids)
        cur.execute(
            "SELECT a.account_id, a.balance, a.iban FROM dbo.account a "
            "JOIN dbo.person p ON p.id = a.person_id "
            "JOIN dbo.center c ON c.center_id = p.center_id "
            f"WHERE c.country_id = ? AND a.account_id IN ({marks})",
            int(country_id),
            *account_ids,
        )
        for account_id, balance, iban in cur.fetchall():
            balances[int(account_id)] = Decimal(str(balance or 0))
            ibans[int(account_id)] = str(iban or "")
    result: list[dict[str, Any]] = []
    for cat_id in sorted(ids, key=lambda i: local_codes.get(i, i)):
        local = int(local_codes.get(cat_id, cat_id))
        if is_journal_forbidden_code(local, roles.get(cat_id)):
            continue
        side, account_id = mapped.get(cat_id, (infer_side(local), None))
        row: dict[str, Any] = {
            "category_id": cat_id,
            "code": local,
            "label": labels.get(cat_id, f"cat_{local}"),
            "side": side,
            "account_id": account_id,
        }
        if account_id is not None:
            row["iban"] = ibans.get(int(account_id), "")
            row["account_balance"] = float(balances.get(int(account_id), Decimal("0")))
        result.append(row)
    return {"categories": result, "remainder_id": int(remainder_id)}


def list_journal(country_id: int, year: int) -> list[dict[str, Any]]:
    from shared.balance_values import AFSCHRIJVING_MARKER, category_labels

    cur = _cursor()
    labels = category_labels(country_id, cur)
    cur.execute(
        "SELECT j.journal_id, j.date, j.category_from, j.category_to, j.amount, j.description "
        "FROM dbo.journal j "
        "JOIN dbo.dim_category d ON d.category_id = j.category_from "
        "WHERE d.country_id = ? AND j.year = ? "
        "ORDER BY j.date, j.journal_id",
        int(country_id),
        int(year),
    )
    rows: list[dict[str, Any]] = []
    for journal_id, booked, cat_from, cat_to, amount, desc in cur.fetchall():
        if str(desc or "").startswith(AFSCHRIJVING_MARKER):
            continue
        when = booked.isoformat() if hasattr(booked, "isoformat") else str(booked)
        rows.append({
            "journal_id": int(journal_id),
            "year": int(year),
            "date": when[:10],
            "category_from": int(cat_from),
            "category_to": int(cat_to),
            "amount": float(amount),
            "description": str(desc or ""),
            "from_label": labels.get(int(cat_from), f"cat_{cat_from}"),
            "to_label": labels.get(int(cat_to), f"cat_{cat_to}"),
        })
    return rows


def save_journal(country_id: int, year: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    from shared.balance_values import (
        afschrijving_like_pattern,
        apply_afschrijvingen,
        category_roles,
        ensure_category_role_booking_rules,
        is_journal_forbidden_code,
    )

    conn = _connection()
    cur = conn.cursor()
    ensure_category_role_booking_rules(cur)
    roles = category_roles(country_id, cur)
    parsed: list[tuple[str, int, int, Decimal, str]] = []
    for item in items:
        booked = str(item["date"])
        cat_from = int(item["category_from"])
        cat_to = int(item["category_to"])
        if is_journal_forbidden_code(cat_from, roles.get(cat_from)):
            raise ValueError(f"Category {cat_from} cannot be used in a journal")
        if is_journal_forbidden_code(cat_to, roles.get(cat_to)):
            raise ValueError(f"Category {cat_to} cannot be used in a journal")
        amount = Decimal(str(item.get("amount", 0)))
        description = str(item.get("description") or "")[:512]
        parsed.append((booked, cat_from, cat_to, amount, description))
    cur.execute(
        "DELETE j FROM dbo.journal j "
        "JOIN dbo.dim_category d ON d.category_id = j.category_from "
        "WHERE d.country_id = ? AND j.year = ? "
        "AND j.description NOT LIKE ? ESCAPE '!'",
        int(country_id),
        int(year),
        afschrijving_like_pattern(),
    )
    for booked, cat_from, cat_to, amount, description in parsed:
        cur.execute(
            "INSERT INTO dbo.journal "
            "(year, date, category_from, category_to, amount, description, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, SYSUTCDATETIME())",
            int(year),
            booked,
            cat_from,
            cat_to,
            amount,
            description,
        )
    apply_afschrijvingen(int(country_id), cur)
    conn.commit()
    return {"ok": True, "year": int(year), "country_id": int(country_id), "saved": len(parsed)}


def list_afschrijvingen_rules(country_id: int) -> dict[str, Any]:
    categories = _afschrijving_category_options(country_id)
    cur = _cursor()
    try:
        cur.execute(
            "SELECT a.id, a.role, a.fraction, dv.local_code, dn.local_code "
            "FROM dbo.afschrijvingen a "
            "JOIN dbo.dim_category dv ON dv.category_id = a.category_id_van "
            "JOIN dbo.dim_category dn ON dn.category_id = a.category_id_naar "
            "WHERE dv.country_id = ? AND dn.country_id = ? "
            "ORDER BY a.id",
            int(country_id),
            int(country_id),
        )
    except Exception as exc:
        if "42S02" in str(exc) or "Invalid object" in str(exc):
            return {"categories": categories, "rows": []}
        raise
    rows: list[dict[str, Any]] = []
    for rule_id, role, fraction, van, naar in cur.fetchall():
        rows.append({
            "id": int(rule_id),
            "role": 1 if role in (1, True) else 0,
            "fraction": float(fraction),
            "local_code_van": int(van),
            "local_code_naar": int(naar),
        })
    return {"categories": categories, "rows": rows}


def _afschrijving_category_options(country_id: int) -> list[dict[str, Any]]:
    from shared.balance_values import (
        category_labels,
        category_local_codes,
        category_roles,
        ensure_category_role_booking_rules,
        infer_side,
        is_journal_forbidden_code,
    )

    cur = _cursor()
    ensure_category_role_booking_rules(cur)
    labels = category_labels(country_id, cur)
    codes = category_local_codes(country_id, cur)
    roles = category_roles(country_id, cur)
    out: list[dict[str, Any]] = []
    for cat_id, local in codes.items():
        try:
            code = int(local)
        except (TypeError, ValueError):
            continue
        if code < 1000 or code > 4999:
            continue
        if is_journal_forbidden_code(int(cat_id), roles.get(int(cat_id))):
            continue
        out.append({
            "local_code": code,
            "label": labels.get(int(cat_id), f"cat_{code}"),
            "side": infer_side(code),
        })
    out.sort(key=lambda row: int(row["local_code"]))
    return out


def save_afschrijvingen_rules(
    country_id: int, items: list[dict[str, Any]]
) -> dict[str, Any]:
    from shared.balance_values import apply_afschrijvingen

    parsed: list[tuple[int, Decimal, int, int]] = []
    for item in items:
        parsed.append((
            1 if item.get("role", 1) in (1, True, "1") else 0,
            Decimal(str(item.get("fraction") or 0)),
            int(item["local_code_van"]),
            int(item["local_code_naar"]),
        ))
    conn = _connection()
    cur = conn.cursor()
    cur.execute("SELECT OBJECT_ID(N'dbo.afschrijvingen', N'U')")
    found = cur.fetchone()
    if found is None or found[0] is None:
        raise ValueError("dbo.afschrijvingen is missing")
    cur.execute(
        "SELECT local_code, category_id FROM dbo.dim_category WHERE country_id = ?",
        int(country_id),
    )
    local_to_id = {
        int(local): int(cat)
        for local, cat in cur.fetchall()
        if local is not None and cat is not None
    }
    missing = [
        code
        for _role, _fraction, van, naar in parsed
        for code in (van, naar)
        if code not in local_to_id
    ]
    if missing:
        raise ValueError(
            "unknown local_code for this country: "
            + ", ".join(str(code) for code in missing)
        )
    cur.execute(
        "DELETE a FROM dbo.afschrijvingen a "
        "JOIN dbo.dim_category d ON d.category_id = a.category_id_van "
        "WHERE d.country_id = ?",
        int(country_id),
    )
    for role, fraction, van, naar in parsed:
        cur.execute(
            "INSERT INTO dbo.afschrijvingen "
            "(role, fraction, category_id_van, category_id_naar) "
            "VALUES (?, ?, ?, ?)",
            role,
            fraction,
            local_to_id[van],
            local_to_id[naar],
        )
    apply_afschrijvingen(int(country_id), cur)
    conn.commit()
    return {
        "ok": True,
        "country_id": int(country_id),
        "saved": len(parsed),
    }
