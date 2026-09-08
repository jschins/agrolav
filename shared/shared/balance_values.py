"""Present-day balance values shared by the balance app and the hub.

Both services compute the balance sheet from the same tables (``dbo.mapping``,
``dbo.balance_opening``, ``dbo.balance_transaction``, ``dbo.balance_journal``
and the live ``dbo.account.balance``), so the derivation lives here once
instead of being duplicated with drift risk:

- the balance app uses it for the sheet (``balance_sheet``);
- the hub uses it to fill the 1000-2999 categories in the client matrix and to
  resolve drill-downs.

All functions work on a pyodbc ``cursor``: the balance app passes a cursor from
its own ``connect()``, the hub passes one from ``user_store._sql_connect()``.
No connection ownership is taken here.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

SPAAR_MARKER = "[spaar-mirror]"

_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


# category_id → (side, account_id | None)
# side: "activa" or "passiva"
_BEHEER_CATEGORY_MAP: dict[int, tuple[str, int | None]] = {
    1000: ("activa", None),       # Gebouwen
    1005: ("activa", None),       # Verbouwingen
    1010: ("activa", None),       # Inventaris
    1015: ("activa", None),       # Autos
    1051: ("activa", 18),         # Bank algemeen
    1052: ("activa", None),       # Spaarrekening
    1053: ("activa", 20),         # Bank huishoudelijke dienst
    1054: ("activa", 17),         # Bank FPU
    1055: ("activa", 19),         # Bank FOH
    1056: ("activa", 21),         # Bank residentie ddkg
    1110: ("activa", None),       # Kruisposten
    1111: ("activa", None),       # r/c K218
    2000: ("passiva", None),      # Eigen vermogen
    2050: ("passiva", None),      # Reserve Vergeer
    2055: ("passiva", None),      # Reserve FF-OG
    2100: ("passiva", None),      # Verlies (computed)
    2500: ("passiva", None),      # Schulden particulieren
}

# The checking → spaarrekening pair for Beheer. Money moves between 1051
# (account 18, NL34..667) and 1052 via transactions that are invisible on the
# spaarrekening side. We reconstruct them by mirroring the 1051 rows whose
# description contains "spaarrekening", with the sign flipped.
_BEHEER_MIRROR: dict[str, object] = {
    "source_account_id": 18,
    "source_category": 1051,
    "target_category": 1052,
    "keyword": "spaarrekening",
}

# Per-country balance configuration:
#   balance_id:  the Eigen vermogen category, computed as the balancing figure
#   result_id:   the Verlies (resultaat) category, derived from dbo.category_total
#   category_map: category_id → (side, account_id | None); account_id links a
#                 bank account whose live balance feeds that category (only
#                 used when dbo.mapping has no entry for that category).
#                 When empty, every dim_category row 1000-4999 is used (side by
#                 range, no account link).
#   mirror:       spaarrekening mirror settings, or None when not used.
#
# Whether a country carries a balance sheet at all is declared in the database
# on ``dbo.country.has_balance`` (set to 1 for sdog and instudo, 0 elsewhere).
_BALANCE_COUNTRIES: dict[int, dict[str, object]] = {
    4: {
        "balance_id": 2000,
        "result_id": 2100,
        "category_map": _BEHEER_CATEGORY_MAP,
        "mirror": _BEHEER_MIRROR,
    },
    5: {
        "balance_id": 2000,
        "result_id": 2100,
        # instudo: fill in its own balance categories and bank-account links.
        "category_map": {},
        "mirror": None,
    },
}

_EMPTY_CONFIG: dict[str, object] = {
    "balance_id": 2000,
    "result_id": 2100,
    "category_map": {},
    "mirror": None,
}


def sql_ident(text: str) -> str | None:
    """Return ``text`` when it is a safe SQL identifier, else ``None``."""
    return text if _IDENT.fullmatch(text or "") else None


def infer_side(cat_id: int) -> str:
    if 1000 <= cat_id <= 1999:
        return "activa"
    if 2000 <= cat_id <= 2999:
        return "passiva"
    if 3000 <= cat_id <= 3999:
        return "kosten"
    return "opbrengsten"


def balance_config(country_id: int) -> dict[str, object]:
    """Per-country balance configuration (falls back to an empty config)."""
    return _BALANCE_COUNTRIES.get(int(country_id), dict(_EMPTY_CONFIG))


def verlies_id(country_id: int) -> int:
    return int(balance_config(country_id).get("result_id") or 2100)


def eigen_vermogen_id(country_id: int) -> int:
    return int(balance_config(country_id).get("balance_id") or 2000)


def country_has_balance(country_id: int, cursor: object) -> bool:
    """``dbo.country.has_balance`` for a country (False when the row is missing)."""
    cursor.execute(
        "SELECT has_balance FROM dbo.country WHERE country_id = ?",
        (int(country_id),),
    )
    row = cursor.fetchone()
    return bool(row[0]) if row else False


def account_links(country_id: int, cursor: object) -> dict[int, int]:
    """category_id → account_id from ``dbo.mapping`` for a country.

    The mapping table records which live bank account feeds each balance
    category (e.g. Beheer 1051 Bank algemeen → account 18).
    """
    cursor.execute(
        "SELECT category_id, account_id FROM dbo.mapping WHERE country_id = ?",
        (int(country_id),),
    )
    return {int(r[0]): int(r[1]) for r in cursor.fetchall()}


def _dim_category_ids(country_id: int, cursor: object) -> set[int]:
    cursor.execute(
        "SELECT DISTINCT category_id FROM dbo.dim_category "
        "WHERE country_id = ? AND category_id BETWEEN 1000 AND 4999",
        (int(country_id),),
    )
    return {int(r[0]) for r in cursor.fetchall()}


def category_labels(country_id: int, cursor: object) -> dict[int, str]:
    """category_id → label from dbo.dim_category (balance categories)."""
    cursor.execute(
        "SELECT category_id, label FROM dbo.dim_category "
        "WHERE country_id = ? AND category_id BETWEEN 1000 AND 4999",
        (int(country_id),),
    )
    return {int(r[0]): str(r[1]) for r in cursor.fetchall()}


def category_map(
    country_id: int, cursor: object
) -> dict[int, tuple[str, int | None]]:
    """category_id → (side, account_id | None) for a balance country.

    Configured categories win; otherwise every dim_category row 1000-4999 is
    used with the side inferred from its code range. ``dbo.mapping`` overrides
    the account link per category.
    """
    configured = balance_config(country_id).get("category_map") or {}
    if configured:
        result = {
            int(c): (str(s), (int(a) if a is not None else None))
            for c, (s, a) in configured.items()
        }
    else:
        result = {
            cat: (infer_side(cat), None) for cat in _dim_category_ids(country_id, cursor)
        }
    for cat_id, account_id in account_links(country_id, cursor).items():
        side, _ = result.get(cat_id, (infer_side(cat_id), None))
        result[int(cat_id)] = (side, account_id)
    return result


def transaction_table(country_id: int, cursor: object) -> str | None:
    """``dbo.transaction_{country.username}`` for a balance country."""
    cursor.execute(
        "SELECT username FROM dbo.country WHERE country_id = ?",
        (int(country_id),),
    )
    row = cursor.fetchone()
    if not row:
        return None
    ident = sql_ident(str(row[0] or ""))
    return f"dbo.transaction_{ident}" if ident else None


def _account_balances(country_id: int, cursor: object) -> dict[int, Decimal]:
    """account_id → balance for the country's persons."""
    cursor.execute(
        "SELECT a.account_id, a.balance FROM dbo.account a "
        "JOIN dbo.person p ON p.id = a.person_id "
        "JOIN dbo.center c ON c.center_id = p.center_id "
        "WHERE c.country_id = ?",
        (int(country_id),),
    )
    return {int(r[0]): _decimal(r[1]) for r in cursor.fetchall()}


def _account_balances_asof(
    country_id: int, year: int, cursor: object, cutoff: date
) -> dict[int, Decimal]:
    current = _account_balances(country_id, cursor)
    if not current:
        return current
    table = transaction_table(country_id, cursor)
    if table is None:
        return current
    later: dict[int, Decimal] = {}
    ids = list(current)
    placeholders = ",".join("?" for _ in ids)
    cursor.execute(
        f"SELECT account_id, SUM(amount) FROM {table} "
        f"WHERE year = ? AND booked_on > ? AND account_id IN ({placeholders}) "
        f"GROUP BY account_id",
        tuple([year, cutoff.isoformat()] + ids),
    )
    for aid, s in cursor.fetchall():
        later[int(aid)] = _decimal(s)
    return {aid: (cur - later.get(aid, Decimal("0"))) for aid, cur in current.items()}


def _opening_balances(country_id: int, year: int, cursor: object) -> dict[int, Decimal]:
    cursor.execute(
        "SELECT category_id, amount FROM dbo.balance_opening "
        "WHERE country_id = ? AND year = ?",
        (int(country_id), int(year)),
    )
    return {int(r[0]): _decimal(r[1]) for r in cursor.fetchall()}


def _journal_balances(
    country_id: int, year: int, cursor: object, *, as_of: date | None = None
) -> dict[int, Decimal]:
    q = (
        "SELECT category_id, SUM(amount) FROM dbo.balance_transaction "
        "WHERE country_id = ? AND year = ?"
    )
    p: list[object] = [int(country_id), int(year)]
    if as_of is not None:
        q += " AND date <= ?"
        p.append(as_of.isoformat())
    q += " GROUP BY category_id"
    cursor.execute(q, tuple(p))
    return {int(r[0]): _decimal(r[1]) for r in cursor.fetchall()}


def _journal_table_exists(cursor: object) -> bool:
    cursor.execute("SELECT OBJECT_ID(N'dbo.balance_journal')")
    return cursor.fetchone()[0] is not None


def _journal_effect(
    country_id: int, year: int, cursor: object, *, as_of: date | None = None
) -> dict[int, Decimal]:
    """category_id → net effect from the hand-edited dbo.balance_journal.

    Each row moves money FROM ``category_from`` TO ``category_to``: the FROM
    category decreases by ``amount`` and the TO category increases by ``amount``.
    The sum over all categories is therefore zero (the sheet stays balanced).
    With ``as_of`` only rows dated on or before that day are included.
    """
    if not _journal_table_exists(cursor):
        return {}
    q = (
        "SELECT category_from, category_to, amount FROM dbo.balance_journal "
        "WHERE country_id = ? AND year = ?"
    )
    p: list[object] = [int(country_id), int(year)]
    if as_of is not None:
        q += " AND date <= ?"
        p.append(as_of.isoformat())
    cursor.execute(q, tuple(p))
    effect: dict[int, Decimal] = {}
    for cat_from, cat_to, amount in cursor.fetchall():
        d = _decimal(amount)
        effect[cat_from] = effect.get(cat_from, Decimal("0")) - d
        effect[cat_to] = effect.get(cat_to, Decimal("0")) + d
    return effect


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _to_cents(value: Decimal) -> int:
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


def balance_category_breakdown(
    country_id: int,
    year: int,
    cursor: object,
    *,
    as_of: date | None = None,
) -> dict[int, tuple[int, str]]:
    """cat_id → (cents, source) for every non-computed balance category.

    Bank categories carry the live ``dbo.account.balance`` (with ``as_of``:
    current minus later movements); non-bank categories carry their opening
    balance. ``dbo.balance_transaction`` sums and the ``dbo.balance_journal``
    effect are added to both. The computed posts (``result_id``/``balance_id``,
    i.e. Verlies and Eigen vermogen) are excluded.
    """
    cfg = balance_config(country_id)
    result_id = int(cfg.get("result_id") or 2100)
    balance_id = int(cfg.get("balance_id") or 2000)
    mapping = category_map(country_id, cursor)
    opening = _opening_balances(country_id, year, cursor)
    journal = _journal_balances(country_id, year, cursor, as_of=as_of)
    effect = _journal_effect(country_id, year, cursor, as_of=as_of)
    if as_of is None:
        acct = _account_balances(country_id, cursor)
    else:
        acct = _account_balances_asof(country_id, year, cursor, as_of)

    amounts: dict[int, tuple[int, str]] = {}
    for cat_id in sorted(mapping):
        if cat_id in (balance_id, result_id):
            continue
        side, account_id = mapping[cat_id]
        if account_id is not None:
            amount = acct.get(account_id, Decimal("0"))
            source = f"account:{account_id}"
        else:
            amount = opening.get(cat_id, Decimal("0"))
            source = "opening"
        journal_amount = journal.get(cat_id)
        if journal_amount is not None:
            amount += journal_amount
            if "+journal" not in source:
                source += "+journal"
        effect_amount = effect.get(cat_id)
        if effect_amount:
            amount += effect_amount
            if "+journal" not in source:
                source += "+journal"
        amounts[cat_id] = (_to_cents(amount), source)
    return amounts


def present_balance_cents(
    country_id: int,
    year: int,
    cursor: object,
    *,
    as_of: date | None = None,
) -> dict[int, int]:
    """cat_id → present-day balance cents for a country/year.

    ``as_of`` restricts the account, journal and mirror amounts to a cutoff
    date; ``None`` means the live, full-year values.
    """
    return {
        cat: cents
        for cat, (cents, _source) in balance_category_breakdown(
            country_id, year, cursor, as_of=as_of
        ).items()
    }


def result_overlay_cents(
    country_id: int,
    year: int,
    cursor: object,
    *,
    as_of: str | None = None,
) -> dict[int, int]:
    """Resultaat effect cents per 3000-4999 category from the balance tables.

    Mirrors the journal/mirror rows into the P&L so the sheet's Verlies post
    agrees with the client's "Saldo" (kosten minus opbrengsten).
    ``dbo.balance_journal`` rows move money FROM ``category_from`` TO
    ``category_to``: the TO category gets the range sign, the FROM category the
    opposite. ``dbo.balance_transaction`` rows contribute their amount with the
    range sign. Sign: 3000-3999 (Kosten) positive, 4000-4999 (Opbrengsten)
    negative. With ``as_of`` (YYYY-MM-DD) only rows dated on or before that day
    are included. Returns ``{}`` when either table is missing.
    """
    for table in ("dbo.balance_journal", "dbo.balance_transaction"):
        cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
        if cursor.fetchone()[0] is None:
            return {}
    dateq = " AND date <= ?" if as_of is not None else ""
    if as_of is not None:
        p: list[object] = [int(country_id), int(year), as_of] * 3
    else:
        p = [int(country_id), int(year)] * 3
    cursor.execute(
        "SELECT c, s, k FROM ("
        f" SELECT category_to AS c, amount AS s, 'T' AS k"
        f" FROM dbo.balance_journal WHERE country_id = ? AND year = ?{dateq}"
        " UNION ALL"
        f" SELECT category_from AS c, amount AS s, 'F' AS k"
        f" FROM dbo.balance_journal WHERE country_id = ? AND year = ?{dateq}"
        " UNION ALL"
        f" SELECT category_id AS c, amount AS s, 'X' AS k"
        f" FROM dbo.balance_transaction WHERE country_id = ? AND year = ?{dateq}"
        ") u WHERE c BETWEEN 3000 AND 4999",
        tuple(p),
    )
    overlay: dict[int, int] = {}
    for category_id, amount, kind in cursor.fetchall():
        try:
            code = int(category_id)
            cents = round(float(amount or 0) * 100)
        except (TypeError, ValueError):
            continue
        side = -1 if code >= 4000 else 1  # K positive, O negative
        if kind == "F":
            side = -side  # FROM inverts the side sign
        overlay[code] = overlay.get(code, 0) + side * cents
    return overlay