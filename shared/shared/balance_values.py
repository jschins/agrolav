"""Present-day balance values shared by the balance app and the hub.

Both services compute the balance sheet from the same tables (``dbo.mapping``,
``dbo.balance_opening``, ``dbo.balance_transaction``, ``dbo.balance_journal``,
the country's ``dbo.transaction_*`` bookings on codes 1000-2999, and the live
``dbo.account.balance``), so the derivation lives here once instead of being
duplicated with drift risk:

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
    1110: ("activa", None),       # Kruisposten
    1111: ("activa", None),       # r/c K218
    2050: ("passiva", None),      # Reserve Vergeer
    2055: ("passiva", None),      # Reserve FF-OG
    2500: ("passiva", None),      # Schulden particulieren
}

# Description fragment on the source-account statement that marks a transfer
# whose counterpart is reconstructed onto the ``mirror`` category.
SPAAR_KEYWORD = "spaarrekening"

# Per-country balance configuration:
#   category_map: ordinary (non-role) category_id → (side, account_id | None).
#                 Bank / plug posts are not listed here; they come from
#                 ``dbo.dim_category.category_role`` plus ``dbo.mapping``.
#                 When empty, every dim_category row 1000-4999 is used (side by
#                 range, no account link).
#
# Whether a country carries a balance sheet at all is declared in the database
# on ``dbo.country.has_balance`` (set to 1 for sdog and instudo, 0 elsewhere).
_BALANCE_COUNTRIES: dict[int, dict[str, object]] = {
    4: {
        "category_map": _BEHEER_CATEGORY_MAP,
    },
    5: {
        "category_map": {},
    },
}

_EMPTY_CONFIG: dict[str, object] = {
    "category_map": {},
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


# ``dbo.dim_category.category_role``:
#   NULL            ordinary booking / journal category
#   remainder       unclassified / default HIT target
#   balance         matrix saldo footer
#   last_booked     matrix datum footer
#   never           Eigen vermogen: never HIT, never journal
#   profit          Verlies / resultaat plug: never HIT, never journal
#   no_hit          live bank posts: never HIT; journals allowed (as A)
#   source          spaar source account (same HIT/journal rules as no_hit)
#   mirror          spaar mirror post (same HIT/journal rules as no_hit)
CATEGORY_ROLE_REMAINDER = "remainder"
CATEGORY_ROLE_NEVER = "never"
CATEGORY_ROLE_PROFIT = "profit"
CATEGORY_ROLE_NO_HIT = "no_hit"
CATEGORY_ROLE_SOURCE = "source"
CATEGORY_ROLE_MIRROR = "mirror"
CATEGORY_FOOTER_ROLES = frozenset({"balance", "last_booked"})
CATEGORY_NO_HIT_ROLES = frozenset(
    {CATEGORY_ROLE_NO_HIT, CATEGORY_ROLE_SOURCE, CATEGORY_ROLE_MIRROR}
)
CATEGORY_COMPUTED_ROLES = frozenset({CATEGORY_ROLE_NEVER, CATEGORY_ROLE_PROFIT})
CATEGORY_HIT_FORBIDDEN_ROLES = frozenset(
    {*CATEGORY_COMPUTED_ROLES, *CATEGORY_NO_HIT_ROLES, *CATEGORY_FOOTER_ROLES}
)
CATEGORY_ROLE_CHECK_VALUES = (
    "N'balance', N'last_booked', N'never', N'profit', N'no_hit', N'source', "
    "N'mirror', N'remainder'"
)

def category_role_text(role: object) -> str:
    return str(role or "").strip().lower()


def is_footer_role(role: object) -> bool:
    return category_role_text(role) in CATEGORY_FOOTER_ROLES


def is_remainder_role(role: object) -> bool:
    return category_role_text(role) == CATEGORY_ROLE_REMAINDER


def is_never_role(role: object) -> bool:
    return category_role_text(role) == CATEGORY_ROLE_NEVER


def is_profit_role(role: object) -> bool:
    return category_role_text(role) == CATEGORY_ROLE_PROFIT


def is_computed_post_role(role: object) -> bool:
    return category_role_text(role) in CATEGORY_COMPUTED_ROLES


def is_hit_forbidden_role(role: object) -> bool:
    return category_role_text(role) in CATEGORY_HIT_FORBIDDEN_ROLES


def is_journal_forbidden_role(role: object) -> bool:
    return is_computed_post_role(role)


def is_hit_forbidden_code(local_code: int, role: object = None) -> bool:
    """HIT onto this local code is invalid when ``category_role`` forbids it."""
    del local_code
    return is_hit_forbidden_role(role)


def is_journal_forbidden_code(local_code: int, role: object = None) -> bool:
    """Journal FROM/TO onto this local code is invalid when the role is computed."""
    del local_code
    return is_journal_forbidden_role(role)


def category_display_name(
    label: object, code: object, role: object
) -> str | None:
    """Matrix / catalog key: coded name, except footer roles which stay bare."""
    text = str(label or "").strip()
    if not text:
        return None
    if is_footer_role(role):
        return text
    if code is None or code == "":
        return None
    return f"{int(code):04d} {text}"


def ensure_category_role_booking_rules(cursor: object) -> None:
    """Widen ``ck_dim_category_role`` and stamp never / profit / no_hit / source / mirror / remainder."""
    cursor.execute(
        "SELECT OBJECT_ID(N'dbo.dim_category', N'U')"
    )
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return
    cursor.execute(
        "SELECT definition FROM sys.check_constraints "
        "WHERE name = N'ck_dim_category_role' "
        "AND parent_object_id = OBJECT_ID(N'dbo.dim_category')"
    )
    existing = cursor.fetchone()
    definition = str(existing[0] or "") if existing else ""
    low = definition.lower()
    tokens = (
        "never",
        "profit",
        "no_hit",
        "source",
        "mirror",
        "remainder",
        "category_role",
    )
    if any(token not in low for token in tokens):
        if existing is not None:
            cursor.execute(
                "ALTER TABLE dbo.dim_category DROP CONSTRAINT ck_dim_category_role"
            )
        cursor.execute(
            "ALTER TABLE dbo.dim_category ADD CONSTRAINT ck_dim_category_role "
            "CHECK (category_role IS NULL OR category_role IN "
            f"({CATEGORY_ROLE_CHECK_VALUES}))"
        )
    cursor.execute("SELECT COL_LENGTH(N'dbo.dim_category', N'is_remainder')")
    remainder_col = cursor.fetchone()
    if remainder_col is not None and remainder_col[0] is not None:
        cursor.execute(
            "UPDATE dbo.dim_category SET category_role = N'remainder' "
            "WHERE is_remainder = 1 AND (category_role IS NULL)"
        )


def is_activa(cat_id: int) -> bool:
    """True for 1000-1999. Passiva and resultaat (3000-4999) share the other class."""
    return 1000 <= int(cat_id) <= 1999


def is_resultaat(cat_id: int) -> bool:
    return 3000 <= int(cat_id) <= 4999


def spaar_mirror(
    country_id: int, cursor: object | None = None
) -> dict[str, object] | None:
    """Spaar pair from ``category_role`` ``source`` / ``mirror`` and ``dbo.mapping``.

    Returns ``source_category``, ``target_category``, ``source_account_id``,
    and ``keyword``, or ``None`` when the country has no complete pair.
    """
    if cursor is None:
        return None
    cursor.execute(
        """
        SELECT d.category_id, d.category_role, m.account_id
        FROM dbo.dim_category d
        LEFT JOIN dbo.mapping m
          ON m.category_id = d.category_id AND m.country_id = d.country_id
        WHERE d.country_id = ?
          AND d.category_role IN (N'source', N'mirror')
        """,
        (int(country_id),),
    )
    source_category: int | None = None
    target_category: int | None = None
    source_account_id: int | None = None
    for category_id, role, account_id in cursor.fetchall():
        if category_id is None:
            continue
        text = category_role_text(role)
        code = int(category_id)
        if text == CATEGORY_ROLE_SOURCE:
            source_category = code
            if account_id is not None:
                source_account_id = int(account_id)
        elif text == CATEGORY_ROLE_MIRROR:
            target_category = code
    if source_category is None or target_category is None or source_account_id is None:
        return None
    return {
        "source_category": source_category,
        "target_category": target_category,
        "source_account_id": source_account_id,
        "keyword": SPAAR_KEYWORD,
    }


def spaar_mirror_target(
    country_id: int, cursor: object | None = None
) -> int | None:
    mirror = spaar_mirror(country_id, cursor)
    return int(mirror["target_category"]) if mirror else None


def spaar_mirror_posted_amount(source_bank_amount: Decimal) -> Decimal:
    """Mirror counterpart of a source-account spaar row.

    Source amount d is the live source-account bank sign (out negative). The
    mirror posts ``-d`` as stored, not through the activa booking sign: money
    leaving the source (d = -X, X > 0) increases the mirror by X, so plug
    2000 is unchanged.
    """
    return -source_bank_amount


def spaar_source_exclude_clause(
    country_id: int, alias: str = "t", *, cursor: object | None = None
) -> tuple[str, list[object]]:
    """SQL that drops source-account spaar-transfer rows (counterpart = mirror).

    ``alias`` is the table alias in the caller (``t`` by default). Use ``""``
    when the FROM table has no alias.
    """
    mirror = spaar_mirror(country_id, cursor)
    if not mirror:
        return "", []
    col = f"{alias}." if alias else ""
    return (
        f" AND NOT ({col}account_id = ? AND "
        f"LOWER(COALESCE({col}description, N'')) LIKE ?)",
        [int(mirror["source_account_id"]), f"%{mirror['keyword']}%"],
    )


def journal_deltas(
    cat_from: int, cat_to: int, amount: Decimal
) -> tuple[Decimal, Decimal]:
    """Signed (FROM, TO) effect that keeps plug 2000 still.

    FROM always ``+= -X``. TO ``+= +X`` when both sides are the same invariance
    class, else ``+= -X``. Classes: activa (1000-1999) vs everything else
    (passiva 2000-2999 and resultaat 3000-4999, since Saldo feeds 2100).
    Kosten and omzet use the same sign (Saldo is the numerical sum).
    """
    delta = amount
    src_delta = -delta
    dst_delta = delta if is_activa(cat_from) == is_activa(cat_to) else -delta
    return src_delta, dst_delta


def journal_leg_amount(
    category_id: int, cat_from: int, cat_to: int, amount: Decimal
) -> Decimal:
    """Effect of one journal row on ``category_id`` (FROM or TO)."""
    src_delta, dst_delta = journal_deltas(int(cat_from), int(cat_to), amount)
    return src_delta if int(category_id) == int(cat_from) else dst_delta


def booking_signed_amount(
    local_code: int,
    amount: Decimal,
    role: object = None,
    *,
    keep_bank_sign: bool = False,
) -> Decimal | None:
    """Overlay for a bank booking of signed amount ``X`` on ``local_code``.

    Transfer from stored category totals (bank sign X) onto the balance
    sheet follows the APR table: A 1000-1999 (except live-bank / spaar)
    ``+= -X``; P 2001-2999 ``+= +X``. ``keep_bank_sign`` skips the A flip
    so the client matrix / transaction list still show the stored sum.
    Bank/spaar and computed posts: ``None``.
    """
    code = int(local_code)
    if is_hit_forbidden_role(role):
        return None
    if 1000 <= code <= 1999:
        return amount if keep_bank_sign else -amount
    if 2001 <= code <= 2999:
        return amount
    return None


def balance_config(country_id: int) -> dict[str, object]:
    """Per-country balance configuration (falls back to an empty config)."""
    return _BALANCE_COUNTRIES.get(int(country_id), dict(_EMPTY_CONFIG))


def role_category_row(
    country_id: int, role: str, cursor: object
) -> tuple[int, int] | None:
    """``(category_id, local_code)`` for this country's ``category_role``, if any."""
    wanted = category_role_text(role)
    if not wanted:
        return None
    cursor.execute(
        """
        SELECT TOP (1) category_id, local_code
        FROM dbo.dim_category
        WHERE country_id = ?
          AND LOWER(LTRIM(RTRIM(category_role))) = ?
        ORDER BY local_code, category_id
        """,
        (int(country_id), wanted),
    )
    row = cursor.fetchone()
    if row is None or row[0] is None or row[1] is None:
        return None
    return int(row[0]), int(row[1])


def role_category_id(country_id: int, role: str, cursor: object) -> int | None:
    """``dim_category.category_id`` for this country's ``category_role``, if any."""
    found = role_category_row(country_id, role, cursor)
    return None if found is None else found[0]


def remainder_category_id(country_id: int, cursor: object) -> int | None:
    return role_category_id(country_id, CATEGORY_ROLE_REMAINDER, cursor)


def remainder_local_code(country_id: int, cursor: object) -> int | None:
    found = role_category_row(country_id, CATEGORY_ROLE_REMAINDER, cursor)
    return None if found is None else found[1]


def verlies_id(country_id: int, cursor: object | None = None) -> int | None:
    """Passiva resultaat post (``category_role = profit``), or ``None``."""
    if cursor is None:
        return None
    return role_category_id(country_id, CATEGORY_ROLE_PROFIT, cursor)


def eigen_vermogen_id(country_id: int, cursor: object | None = None) -> int | None:
    """Eigen vermogen plug (``category_role = never``), or ``None``."""
    if cursor is None:
        return None
    return role_category_id(country_id, CATEGORY_ROLE_NEVER, cursor)


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
    category (the ``source`` post is the spaar checking account).
    """
    cursor.execute(
        "SELECT category_id, account_id FROM dbo.mapping WHERE country_id = ?",
        (int(country_id),),
    )
    return {int(r[0]): int(r[1]) for r in cursor.fetchall()}


def _dim_category_ids(country_id: int, cursor: object) -> set[int]:
    cursor.execute(
        "SELECT DISTINCT category_id FROM dbo.dim_category "
        "WHERE country_id = ? AND local_code BETWEEN 1000 AND 4999",
        (int(country_id),),
    )
    return {int(r[0]) for r in cursor.fetchall()}


def category_labels(country_id: int, cursor: object) -> dict[int, str]:
    """category_id → label from dbo.dim_category (balance categories)."""
    cursor.execute(
        "SELECT category_id, label FROM dbo.dim_category "
        "WHERE country_id = ? AND local_code BETWEEN 1000 AND 4999",
        (int(country_id),),
    )
    return {int(r[0]): str(r[1]) for r in cursor.fetchall()}


def category_local_codes(country_id: int, cursor: object) -> dict[int, int]:
    """category_id → local_code for a country."""
    cursor.execute(
        "SELECT category_id, local_code FROM dbo.dim_category WHERE country_id = ?",
        (int(country_id),),
    )
    out: dict[int, int] = {}
    for row in cursor.fetchall():
        if row is None or row[0] is None or row[1] is None:
            continue
        try:
            out[int(row[0])] = int(row[1])
        except (TypeError, ValueError):
            continue
    return out


def resolve_category_id(codes: dict[int, int], key: int) -> int:
    """Return the ``category_id`` for ``key`` when ``key`` is an id or a local_code."""
    wanted = int(key)
    if wanted in codes:
        return wanted
    for cat_id, local_code in codes.items():
        if local_code == wanted:
            return cat_id
    return wanted


def category_roles(country_id: int, cursor: object) -> dict[int, str]:
    """category_id → ``category_role`` text (empty string when NULL)."""
    cursor.execute(
        "SELECT category_id, category_role FROM dbo.dim_category "
        "WHERE country_id = ? AND local_code BETWEEN 1000 AND 4999",
        (int(country_id),),
    )
    return {
        int(r[0]): str(r[1] or "").strip()
        for r in cursor.fetchall()
        if r[0] is not None
    }


def category_map(
    country_id: int, cursor: object
) -> dict[int, tuple[str, int | None]]:
    """category_id → (side, account_id | None) for a balance country.

    Configured categories win; otherwise every dim_category row 1000-4999 is
    used with the side inferred from its code range. ``dbo.mapping`` overrides
    the account link per category.
    """
    codes = category_local_codes(country_id, cursor)
    configured = balance_config(country_id).get("category_map") or {}
    if configured:
        result = {
            resolve_category_id(codes, int(c)): (
                str(s),
                (int(a) if a is not None else None),
            )
            for c, (s, a) in configured.items()
        }
    else:
        result = {
            cat: (infer_side(codes.get(cat, cat)), None)
            for cat in _dim_category_ids(country_id, cursor)
        }
    roles = category_roles(country_id, cursor)
    for cat_id, role in roles.items():
        if is_computed_post_role(role):
            result.pop(cat_id, None)
            continue
        if category_role_text(role) in CATEGORY_NO_HIT_ROLES and cat_id not in result:
            result[cat_id] = (infer_side(codes.get(cat_id, cat_id)), None)
    for cat_id, account_id in account_links(country_id, cursor).items():
        side, _ = result.get(
            cat_id, (infer_side(codes.get(cat_id, cat_id)), None)
        )
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


def spaar_source_sums(
    country_id: int, year: int, cursor: object, *, as_of: date | None = None
) -> dict[int, Decimal]:
    """category_id → bank-sign sum of source-account spaar-keyword rows.

    Those rows already move the live source account. Their counterpart is the
    ``mirror`` post (``-d`` as stored). They must not also move HIT categories
    or Saldo.
    """
    mirror = spaar_mirror(country_id, cursor)
    table = transaction_table(country_id, cursor)
    if mirror is None or table is None:
        return {}
    cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return {}
    q = (
        f"SELECT t.category_id, SUM(t.amount) FROM {table} t "
        "JOIN dbo.person p ON p.id = t.person_id "
        "JOIN dbo.center n ON n.center_id = p.center_id "
        "WHERE n.country_id = ? AND t.year = ? AND t.bank_id IS NULL "
        "AND t.account_id = ? AND LOWER(COALESCE(t.description, N'')) LIKE ?"
    )
    p: list[object] = [
        int(country_id),
        int(year),
        int(mirror["source_account_id"]),
        f"%{mirror['keyword']}%",
    ]
    if as_of is not None:
        q += " AND t.booked_on <= ?"
        p.append(as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of))
    q += " GROUP BY t.category_id"
    cursor.execute(q, tuple(p))
    return {
        int(category_id): _decimal(amount)
        for category_id, amount in cursor.fetchall()
        if category_id is not None
    }


def spaar_source_result_amounts(
    country_id: int, year: int, cursor: object, *, as_of: date | None = None
) -> dict[int, Decimal]:
    """Spaar-source sums that landed on 3000-4999 (must not enter Saldo/2100)."""
    return {
        code: amount
        for code, amount in spaar_source_sums(
            country_id, year, cursor, as_of=as_of
        ).items()
        if is_resultaat(code)
    }


def _journal_balances(
    country_id: int, year: int, cursor: object, *, as_of: date | None = None
) -> dict[int, Decimal]:
    """category_id → stored ``dbo.balance_transaction`` sum (spaar-mirror as-is).

    Mirror amounts are already ``-d`` from generate time; they are not passed
    through the activa booking sign.
    """
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


def _booking_balances(
    country_id: int,
    year: int,
    cursor: object,
    *,
    as_of: date | None = None,
    keep_bank_sign: bool = False,
) -> dict[int, Decimal]:
    """category_id → signed overlay from the country's booking table (1000-2999).

    Consolidated rows only (``bank_id IS NULL``). Amount X is the bank sign
    (in +, out -). Activa 1000-1999 get ``-X``; passiva 2001-2999 get ``+X``.
    Codes with a HIT-forbidden ``category_role`` (live bank, spaar pair,
    ``never``, ``profit``) are skipped. Source-account spaar-keyword rows are excluded (their
    counterpart is the mirror post). P&L (3000-4999)
    stays on the resultaat sheet as ``+X``. ``{}`` when the table is missing.
    """
    table = transaction_table(country_id, cursor)
    if table is None:
        return {}
    cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return {}
    q = (
        f"SELECT t.category_id, d.local_code, SUM(t.amount), d.category_role FROM {table} t "
        "JOIN dbo.person p ON p.id = t.person_id "
        "JOIN dbo.center n ON n.center_id = p.center_id "
        "JOIN dbo.dim_category d ON d.category_id = t.category_id "
        "WHERE n.country_id = ? AND t.year = ? AND t.bank_id IS NULL "
        "AND d.local_code BETWEEN 1000 AND 2999 "
        "AND (d.category_role IS NULL OR d.category_role = N'remainder')"
    )
    p: list[object] = [int(country_id), int(year)]
    exclude_sql, exclude_params = spaar_source_exclude_clause(
        country_id, cursor=cursor
    )
    q += exclude_sql
    p.extend(exclude_params)
    if as_of is not None:
        q += " AND t.booked_on <= ?"
        p.append(as_of.isoformat())
    q += " GROUP BY t.category_id, d.local_code, d.category_role"
    cursor.execute(q, tuple(p))
    result: dict[int, Decimal] = {}
    for item in cursor.fetchall():
        if item is None or len(item) < 3:
            continue
        category_id, local_code, amount = item[0], item[1], item[2]
        role = item[3] if len(item) > 3 else None
        if category_id is None or local_code is None:
            continue
        signed = booking_signed_amount(
            int(local_code),
            _decimal(amount),
            role,
            keep_bank_sign=keep_bank_sign,
        )
        if signed is None:
            continue
        result[int(category_id)] = signed
    return result


def _journal_table_exists(cursor: object) -> bool:
    cursor.execute("SELECT OBJECT_ID(N'dbo.balance_journal')")
    return cursor.fetchone()[0] is not None


def _journal_effect(
    country_id: int, year: int, cursor: object, *, as_of: date | None = None
) -> dict[int, Decimal]:
    """category_id → net effect from the hand-edited dbo.balance_journal.

    Amount X is a transfer whose signs keep Eigen vermogen (2000) still:
    FROM ``+= -X``; TO ``+= +X`` when FROM and TO are the same class (both
    activa, or both passiva/resultaat), else TO ``+= -X``. FROM 1110 TO 3110
    of 9000 therefore moves -9000 onto both 1110 and 3110. With ``as_of`` only
    rows dated on or before that day are included.
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
    roles = category_roles(country_id, cursor)
    codes = category_local_codes(country_id, cursor)
    cursor.execute(q, tuple(p))
    effect: dict[int, Decimal] = {}
    for cat_from, cat_to, amount in cursor.fetchall():
        src, dst = int(cat_from), int(cat_to)
        if is_journal_forbidden_code(src, roles.get(src)) or is_journal_forbidden_code(
            dst, roles.get(dst)
        ):
            continue
        src_delta, dst_delta = journal_deltas(
            codes.get(src, src), codes.get(dst, dst), _decimal(amount)
        )
        effect[src] = effect.get(src, Decimal("0")) + src_delta
        effect[dst] = effect.get(dst, Decimal("0")) + dst_delta
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
    keep_bank_sign: bool = False,
) -> dict[int, tuple[int, str]]:
    """cat_id → (cents, source) for every non-computed balance category.

    Bank categories carry the live ``dbo.account.balance`` (with ``as_of``:
    current minus later movements); non-bank categories carry their opening
    balance. ``dbo.balance_transaction`` sums, ``dbo.balance_journal`` effects,
    and signed booking rows from ``dbo.transaction_{country}`` (codes 1000-2999,
    activa ``-X`` / passiva ``+X``) are added to non-bank posts. Bank-linked
    posts skip the booking sum so the live account is not counted twice.
    Bookings onto live-bank / spaar roles are ignored. The spaar ``mirror``
    post is always opening + stored ``balance_transaction`` (already ``-d``),
    never a live account and never the activa booking sign. The computed
    posts (``never`` / ``profit``) are excluded.
    """
    roles = category_roles(country_id, cursor)
    result_id = verlies_id(country_id, cursor)
    balance_id = eigen_vermogen_id(country_id, cursor)
    computed = {
        cat_id
        for cat_id, role in roles.items()
        if is_computed_post_role(role)
    }
    computed.update(i for i in (result_id, balance_id) if i is not None)
    mirror_target = spaar_mirror_target(country_id, cursor)
    mapping = category_map(country_id, cursor)
    opening = _opening_balances(country_id, year, cursor)
    journal = _journal_balances(country_id, year, cursor, as_of=as_of)
    effect = _journal_effect(country_id, year, cursor, as_of=as_of)
    bookings = _booking_balances(
        country_id, year, cursor, as_of=as_of, keep_bank_sign=keep_bank_sign
    )
    if as_of is None:
        acct = _account_balances(country_id, cursor)
    else:
        acct = _account_balances_asof(country_id, year, cursor, as_of)

    amounts: dict[int, tuple[int, str]] = {}
    for cat_id in sorted(mapping):
        if cat_id in computed:
            continue
        side, account_id = mapping[cat_id]
        is_mirror = mirror_target is not None and cat_id == mirror_target
        if account_id is not None and not is_mirror:
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
        if account_id is None and not is_mirror:
            booking_amount = bookings.get(cat_id)
            if booking_amount is not None:
                amount += booking_amount
                if "+bookings" not in source:
                    source += "+bookings"
        amounts[cat_id] = (_to_cents(amount), source)
    return amounts


def present_balance_cents(
    country_id: int,
    year: int,
    cursor: object,
    *,
    as_of: date | None = None,
    keep_bank_sign: bool = False,
) -> dict[int, int]:
    """cat_id → present-day balance cents for a country/year.

    ``as_of`` restricts the account, journal and mirror amounts to a cutoff
    date; ``None`` means the live, full-year values. Default applies the APR
    sign (A ``-X``). ``keep_bank_sign`` keeps stored X for the client matrix.
    """
    return {
        cat: cents
        for cat, (cents, _source) in balance_category_breakdown(
            country_id,
            year,
            cursor,
            as_of=as_of,
            keep_bank_sign=keep_bank_sign,
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

    Journals use ``journal_deltas`` so Saldo (and passiva 2100) stay the
    numerical sum of 3000-4999: K and O share the same sign. Mirror rows in
    ``dbo.balance_transaction`` add their amount as stored. With ``as_of``
    (YYYY-MM-DD) only rows dated on or before that day are included. Returns
    ``{}`` when either table is missing.
    """
    for table in ("dbo.balance_journal", "dbo.balance_transaction"):
        cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
        if cursor.fetchone()[0] is None:
            return {}
    dateq = " AND date <= ?" if as_of is not None else ""
    params: list[object] = [int(country_id), int(year)]
    if as_of is not None:
        params.append(as_of)
    overlay: dict[int, int] = {}
    codes = category_local_codes(country_id, cursor)
    cursor.execute(
        "SELECT category_from, category_to, amount FROM dbo.balance_journal "
        f"WHERE country_id = ? AND year = ?{dateq}",
        tuple(params),
    )
    for cat_from, cat_to, amount in cursor.fetchall():
        try:
            src, dst = int(cat_from), int(cat_to)
        except (TypeError, ValueError):
            continue
        src_delta, dst_delta = journal_deltas(
            codes.get(src, src), codes.get(dst, dst), _decimal(amount)
        )
        if is_resultaat(codes.get(src, src)):
            overlay[src] = overlay.get(src, 0) + _to_cents(src_delta)
        if is_resultaat(codes.get(dst, dst)):
            overlay[dst] = overlay.get(dst, 0) + _to_cents(dst_delta)
    cursor.execute(
        "SELECT category_id, amount FROM dbo.balance_transaction "
        f"WHERE country_id = ? AND year = ?{dateq}",
        tuple(params),
    )
    for category_id, amount in cursor.fetchall():
        try:
            code = int(category_id)
        except (TypeError, ValueError):
            continue
        if not is_resultaat(codes.get(code, code)):
            continue
        overlay[code] = overlay.get(code, 0) + _to_cents(_decimal(amount))
    return overlay