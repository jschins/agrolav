"""Enable Banking application credentials in ``dbo.enable_connection``.

JWT signing uses ``app_id`` + ``pem`` from SQL. PEM files are not written to disk.
A connection row can exist for a person before any ``dbo.account`` rows.
"""
from __future__ import annotations

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
