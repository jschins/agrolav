"""Enable Banking application credentials in ``dbo.enable_connection``.

JWT signing uses ``app_id`` + ``pem`` from SQL. PEM files are not written to disk.
A connection row can exist for a person before any ``dbo.account`` rows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _cursor():
    from app import user_store

    if not user_store.database_url():
        return None
    user_store.init_user_store()
    return user_store._sql_connect().cursor()


def _person_id(cursor, username: str) -> int | None:
    name = str(username or "").strip()
    if not name:
        return None
    cursor.execute(
        "SELECT id FROM dbo.person WHERE username = ? COLLATE Latin1_General_CI_AI",
        (name,),
    )
    row = cursor.fetchone()
    return int(row[0]) if row else None


def _connection_ids_for_person(cursor, person_id: int) -> list[int]:
    cursor.execute(
        """
        SELECT connection_id FROM dbo.enable_connection WHERE person_id = ?
        UNION
        SELECT DISTINCT connection_id FROM dbo.account
        WHERE person_id = ? AND connection_id IS NOT NULL
        """,
        (person_id, person_id),
    )
    return [int(row[0]) for row in cursor.fetchall() if row[0] is not None]


def credentials_for_person(username: str) -> tuple[str, str] | None:
    """``(app_id, pem)`` for JWT signing, or None."""
    cursor = _cursor()
    if cursor is None:
        return None
    person_id = _person_id(cursor, username)
    if person_id is None:
        return None
    ids = _connection_ids_for_person(cursor, person_id)
    if not ids:
        return None
    placeholders = ",".join("?" for _ in ids)
    cursor.execute(
        f"""
        SELECT TOP 1 app_id, pem
        FROM dbo.enable_connection
        WHERE connection_id IN ({placeholders})
          AND pem IS NOT NULL
          AND LTRIM(RTRIM(pem)) <> N''
        ORDER BY CASE WHEN app_id IS NULL OR LTRIM(RTRIM(app_id)) = N'' THEN 1 ELSE 0 END,
                 connection_id
        """,
        tuple(ids),
    )
    row = cursor.fetchone()
    if not row:
        return None
    app_id = str(row[0] or "").strip()
    pem = str(row[1] or "").strip()
    if not app_id or not pem or "PRIVATE KEY" not in pem:
        return None
    return app_id, pem + ("\n" if not pem.endswith("\n") else "")


def person_has_pem(username: str) -> bool:
    return credentials_for_person(username) is not None


def person_has_pem_light(username: str) -> bool:
    """Cheap existence check: connection row with a PEM present (no blob read)."""
    cursor = _cursor()
    if cursor is None:
        return False
    person_id = _person_id(cursor, username)
    if person_id is None:
        return False
    cursor.execute(
        """
        SELECT TOP 1 1
        FROM dbo.enable_connection
        WHERE person_id = ?
          AND pem IS NOT NULL
          AND LTRIM(RTRIM(pem)) <> N''
        """,
        (person_id,),
    )
    return cursor.fetchone() is not None


def center_has_pem(center: str) -> bool:
    cursor = _cursor()
    if cursor is None:
        return False
    name = str(center or "").strip()
    if not name:
        return False
    cursor.execute(
        """
        SELECT TOP 1 1
        FROM dbo.enable_connection ec
        INNER JOIN dbo.person p ON p.id = ec.person_id
        INNER JOIN dbo.center n ON n.center_id = p.center_id
        WHERE n.username = ? COLLATE Latin1_General_CI_AI
          AND ec.pem IS NOT NULL
          AND LTRIM(RTRIM(ec.pem)) <> N''
        """,
        (name,),
    )
    if cursor.fetchone():
        return True
    cursor.execute(
        """
        SELECT TOP 1 1
        FROM dbo.account a
        INNER JOIN dbo.enable_connection ec ON ec.connection_id = a.connection_id
        INNER JOIN dbo.person p ON p.id = a.person_id
        INNER JOIN dbo.center n ON n.center_id = p.center_id
        WHERE n.username = ? COLLATE Latin1_General_CI_AI
          AND ec.pem IS NOT NULL
          AND LTRIM(RTRIM(ec.pem)) <> N''
        """,
        (name,),
    )
    return cursor.fetchone() is not None


def person_consent_ready(username: str) -> bool | None:
    """Return SQL consent readiness, or None when SQL is not configured."""
    cursor = _cursor()
    if cursor is None:
        return None
    person_id = _person_id(cursor, username)
    if person_id is None:
        return False
    cursor.execute(
        """
        SELECT TOP 1 ec.session_id, ec.valid_until,
            (SELECT COUNT(*) FROM dbo.account a WHERE a.person_id = p.id) AS account_count
        FROM dbo.person p
        LEFT JOIN dbo.enable_connection ec ON ec.person_id = p.id
        WHERE p.id = ?
        ORDER BY ec.connection_id DESC
        """,
        (person_id,),
    )
    row = cursor.fetchone()
    if row is None or not str(row[0] or "").strip() or int(row[2] or 0) == 0:
        return False
    valid_until = row[1]
    if valid_until is None:
        return False
    if isinstance(valid_until, datetime):
        expires = valid_until
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    else:
        try:
            expires = datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
        except ValueError:
            return False
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    return expires >= datetime.now(timezone.utc)


def person_has_transactions(username: str) -> bool:
    """True when the person already has transactions in their country table."""
    cursor = _cursor()
    if cursor is None:
        return False
    person_id = _person_id(cursor, username)
    if person_id is None:
        return False
    cursor.execute(
        """
        SELECT TOP 1 c.username
        FROM dbo.person p
        INNER JOIN dbo.country c ON c.country_id = p.country_id
        WHERE p.id = ?
        """,
        (person_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return False
    from app.sql_replica import _transaction_table

    table = _transaction_table(str(row[0] or ""))
    if table is None:
        return False
    from app.sql_layout import ensure_transaction_table

    if not ensure_transaction_table(country=str(row[0] or "")):
        return False
    cursor.execute(
        f"SELECT TOP 1 transaction_id FROM {table} WHERE person_id = ?",
        (person_id,),
    )
    return cursor.fetchone() is not None


def person_country_username(username: str) -> str:
    """``dbo.country.username`` for the person (``nederland``, ``united_kingdom``, ...)."""
    cursor = _cursor()
    if cursor is None:
        return ""
    person_id = _person_id(cursor, username)
    if person_id is None:
        return ""
    cursor.execute(
        """
        SELECT TOP 1 c.username
        FROM dbo.person p
        INNER JOIN dbo.country c ON c.country_id = p.country_id
        WHERE p.id = ?
        """,
        (person_id,),
    )
    row = cursor.fetchone()
    return str(row[0] or "") if row else ""


def person_aspsp(username: str) -> str:
    """ASPSP hint from ``dbo.account.format`` (top account for the person)."""
    cursor = _cursor()
    if cursor is None:
        return ""
    person_id = _person_id(cursor, username)
    if person_id is None:
        return ""
    cursor.execute(
        """
        SELECT TOP 1 format
        FROM dbo.account
        WHERE person_id = ?
          AND format IS NOT NULL
          AND LTRIM(RTRIM(format)) <> N''
        ORDER BY account_id
        """,
        (person_id,),
    )
    row = cursor.fetchone()
    return str(row[0] or "") if row else ""


def consent_ready_people(center: str) -> list[str]:
    """Usernames in ``center`` whose bank consent is active in SQL.

    Mirrors ``person_consent_ready`` (session present, ``valid_until`` in the
    future, at least one account) so the client can recover readiness after a
    hub restart wiped the in-memory callback markers.
    """
    cursor = _cursor()
    if cursor is None:
        return []
    name = str(center or "").strip()
    if not name:
        return []
    cursor.execute(
        """
        SELECT p.username
        FROM dbo.person p
        INNER JOIN dbo.center n ON n.center_id = p.center_id
        WHERE n.username = ? COLLATE Latin1_General_CI_AI
          AND EXISTS (
              SELECT TOP 1 1
              FROM dbo.enable_connection ec
              WHERE ec.person_id = p.id
                AND ec.session_id IS NOT NULL
                AND LTRIM(RTRIM(ec.session_id)) <> N''
                AND ec.valid_until >= GETUTCDATE()
          )
          AND EXISTS (
              SELECT TOP 1 1
              FROM dbo.account a
              WHERE a.person_id = p.id
          )
        ORDER BY p.username
        """,
        (name,),
    )
    return [str(row[0]) for row in cursor.fetchall() if row[0]]


_PENDING_TTL_MINUTES = 30


def _prune_consent_pending_rows(cursor) -> None:
    cursor.execute(
        """
        DELETE FROM dbo.consent_pending
        WHERE created_at < DATEADD(minute, ?, GETUTCDATE())
        """,
        (-_PENDING_TTL_MINUTES,),
    )


def upsert_consent_pending(state: str, *, center: str, person_name: str) -> None:
    """Persist the ``state -> person_name`` mapping across hub restarts.

    Best-effort: callers also keep their in-memory copy. No-op when SQL is
    not configured or the table is missing.
    """
    cursor = _cursor()
    if cursor is None:
        return
    token = str(state or "").strip()
    if not token:
        return
    try:
        _prune_consent_pending_rows(cursor)
        person = str(person_name or "").strip()
        cursor.execute(
            """
            UPDATE dbo.consent_pending
            SET center = ?, person_name = ?, created_at = GETUTCDATE()
            WHERE state = ?
            """,
            (str(center or "").strip(), person, token),
        )
        if cursor.rowcount == 0:
            cursor.execute(
                """
                INSERT INTO dbo.consent_pending (state, center, person_name, created_at)
                VALUES (?, ?, ?, GETUTCDATE())
                """,
                (token, str(center or "").strip(), person),
            )
        cursor.connection.commit()
    except Exception:  # noqa: BLE001
        pass


def take_consent_pending(state: str) -> dict[str, Any] | None:
    """Pop and return the persisted ``state`` row, or None."""
    cursor = _cursor()
    if cursor is None:
        return None
    token = str(state or "").strip()
    if not token:
        return None
    try:
        _prune_consent_pending_rows(cursor)
        cursor.execute(
            """
            SELECT TOP 1 center, person_name
            FROM dbo.consent_pending
            WHERE state = ?
            ORDER BY created_at DESC
            """,
            (token,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        cursor.execute("DELETE FROM dbo.consent_pending WHERE state = ?", (token,))
        cursor.connection.commit()
        return {
            "center": str(row[0] or ""),
            "person_name": str(row[1] or ""),
        }
    except Exception:  # noqa: BLE001
        return None


def delete_consent_pending(state: str) -> None:
    """Remove a persisted ``state`` row (no-op when SQL is not configured)."""
    cursor = _cursor()
    if cursor is None:
        return
    token = str(state or "").strip()
    if not token:
        return
    try:
        cursor.execute("DELETE FROM dbo.consent_pending WHERE state = ?", (token,))
        cursor.connection.commit()
    except Exception:  # noqa: BLE001
        pass


def person_title_from_bank_accounts(accounts: list[dict[str, Any]]) -> str:
    """Person title from Enable Banking account-holder name (not the login username)."""
    for account in accounts:
        if not isinstance(account, dict):
            continue
        iban = str(account.get("iban") or "").strip()
        nested = account.get("account_id")
        if isinstance(nested, dict) and not iban:
            iban = str(nested.get("iban") or "").strip()
        for key in ("name", "holder", "title", "account_name"):
            text = str(account.get(key) or "").strip()
            if text and text != iban:
                return text[:256]
    return ""


def upsert_person_accounts(username: str, accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist every account returned by Enable Banking for a person."""
    cursor = _cursor()
    if cursor is None:
        raise RuntimeError("SQL Server is not configured")
    person_id = _person_id(cursor, username)
    if person_id is None:
        raise ValueError(f"Unknown person login: {username}")
    cursor.execute(
        "SELECT TOP 1 connection_id FROM dbo.enable_connection WHERE person_id = ? ORDER BY connection_id",
        (person_id,),
    )
    connection = cursor.fetchone()
    if connection is None:
        raise ValueError(f"No Enable Banking connection for person: {username}")
    connection_id = int(connection[0])
    result: list[dict[str, Any]] = []
    for account in accounts:
        uid = str(account.get("uid") or "").strip()[:128]
        if not uid:
            continue
        iban = str(account.get("iban") or "").strip()[:64]
        placeholder_iban = not iban or iban.lower() == "credit card"
        if placeholder_iban:
            iban = iban or "Credit Card"
        name = (
            str(
                account.get("name")
                or account.get("holder")
                or account.get("title")
                or iban
            ).strip()[:64]
            or iban
        )
        balance = str(account.get("balance") or "0").strip().replace(",", ".") or "0"
        cursor.execute(
            """
            SELECT TOP 1 account_id
            FROM dbo.account
            WHERE person_id = ? AND uid = ?
            ORDER BY account_id
            """,
            (person_id, uid),
        )
        row = cursor.fetchone()
        if row is None and not placeholder_iban:
            # Unique key is (person_id, iban). Match even when the row already
            # has a uid — a new Enable Banking uid for the same IBAN must
            # update, not insert.
            cursor.execute(
                """
                SELECT TOP 1 account_id
                FROM dbo.account
                WHERE person_id = ? AND iban = ?
                ORDER BY account_id
                """,
                (person_id, iban),
            )
            row = cursor.fetchone()
        if row is None:
            cursor.execute(
                """
                INSERT INTO dbo.account
                    (person_id, iban, account_name, format, balance, connection_id, uid, identification_hash)
                OUTPUT INSERTED.account_id
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    person_id,
                    iban,
                    name,
                    str(account.get("aspsp") or "").strip()[:64] or None,
                    balance,
                    connection_id,
                    uid,
                    str(account.get("identification_hash") or "").strip()[:128] or None,
                ),
            )
            account_id = int(cursor.fetchone()[0])
        else:
            account_id = int(row[0])
            cursor.execute(
                """
                UPDATE dbo.account
                SET account_name = ?, balance = ?, connection_id = ?, uid = ?, identification_hash = ?
                WHERE account_id = ?
                """,
                (
                    name,
                    balance,
                    connection_id,
                    uid,
                    str(account.get("identification_hash") or "").strip()[:128] or None,
                    account_id,
                ),
            )
        result.append({"account_id": account_id, "uid": uid, "iban": iban, "account_name": name})
    title = person_title_from_bank_accounts(accounts)
    if title:
        cursor.execute(
            "UPDATE dbo.person SET title = ? WHERE id = ?",
            (title, person_id),
        )
    cursor.execute(
        "UPDATE dbo.person SET number_of_accounts = (SELECT COUNT(*) FROM dbo.account WHERE person_id = ?) WHERE id = ?",
        (person_id, person_id),
    )
    from app import user_store

    user_store._sql_connect().commit()
    return result


def update_person_connection(username: str, connection: dict[str, Any]) -> int:
    """Persist the Enable Banking session metadata for a person."""
    cursor = _cursor()
    if cursor is None:
        raise RuntimeError("SQL Server is not configured")
    person_id = _person_id(cursor, username)
    if person_id is None:
        raise ValueError(f"Unknown person login: {username}")
    session_id = str(connection.get("session_id") or "").strip() or None
    valid_until = str(connection.get("valid_until") or "").strip() or None
    created_at = str(connection.get("created_at") or "").strip() or None
    cursor.execute(
        """
        SELECT TOP 1 connection_id
        FROM dbo.enable_connection
        WHERE person_id = ?
        ORDER BY CASE WHEN app_id IS NULL OR LTRIM(RTRIM(app_id)) = N'' THEN 1 ELSE 0 END,
                 connection_id DESC
        """,
        (person_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"No Enable Banking connection for person: {username}")
    connection_id = int(row[0])
    cursor.execute(
        """
        UPDATE dbo.enable_connection
        SET session_id = ?, valid_until = ?, created_at = ?
        WHERE connection_id = ?
        """,
        (session_id, valid_until, created_at, connection_id),
    )
    from app import user_store

    user_store._sql_connect().commit()
    return connection_id


def upsert_person_pem(username: str, *, app_id: str, pem: str) -> dict[str, Any]:
    """Write application id + PEM for this person. Does not write files."""
    app = str(app_id or "").strip()
    text = str(pem or "").strip()
    if not app:
        raise ValueError("app_id is empty")
    if "PRIVATE KEY" not in text:
        raise ValueError("File does not look like an RSA private key PEM")
    text = text + "\n"
    cursor = _cursor()
    if cursor is None:
        raise RuntimeError("SQL Server is not configured")
    from app import user_store

    person_id = _person_id(cursor, username)
    if person_id is None:
        raise ValueError(f"Unknown person login: {username}")
    ids = _connection_ids_for_person(cursor, person_id)
    if ids:
        placeholders = ",".join("?" for _ in ids)
        cursor.execute(
            f"""
            UPDATE dbo.enable_connection
            SET app_id = ?, pem = ?, person_id = COALESCE(person_id, ?)
            WHERE connection_id IN ({placeholders})
            """,
            (app[:128], text, person_id, *ids),
        )
        connection_id = ids[0]
    else:
        cursor.execute(
            """
            INSERT INTO dbo.enable_connection (person_id, app_id, pem)
            OUTPUT INSERTED.connection_id
            VALUES (?, ?, ?)
            """,
            (person_id, app[:128], text),
        )
        connection_id = int(cursor.fetchone()[0])
    user_store._sql_connect().commit()
    return {"connection_id": connection_id, "app_id": app, "person_id": person_id}
