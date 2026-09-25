"""Present-day balance values shared by the balance app and the hub.

Both services compute the balance sheet from the same tables (``dbo.mapping_banks``,
``dbo.balance_opening``, ``dbo.transaction_mirror``, ``dbo.journal``,
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

import logging
import re
from collections.abc import Callable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_log = logging.getLogger("balance.sheet")

SPAAR_MARKER = "[spaar-mirror]"
AFSCHRIJVING_MARKER = "[afschrijving]"

_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class CatalogError(ValueError):
    """Required ``dim_category`` role or mapping row is missing."""


# Description fragment on the source-account statement that marks a transfer
# whose counterpart is reconstructed onto the ``mirror`` category.
SPAAR_KEYWORD = "spaarrekening"


def sql_ident(text: str) -> str | None:
    """Return ``text`` when it is a safe SQL identifier, else ``None``."""
    return text if _IDENT.fullmatch(text or "") else None


def infer_side(cat_id: int) -> str:
    code = int(cat_id)
    # 1099 is the country-5 NL46→NL84 cross-posting (category_id 11099).
    if code == 1099 or 1000 <= code <= 1999:
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
#   equity          Eigen vermogen: no HIT, no journal
#   profit          Verlies / resultaat plug: no HIT, no journal
#   bank            live bank posts: no HIT; journals allowed (as A)
#   source          spaar source account (same HIT/journal rules as bank)
#   mirror          spaar mirror post: HIT allowed; journals allowed (as A)
CATEGORY_ROLE_REMAINDER = "remainder"
CATEGORY_ROLE_EQUITY = "equity"
CATEGORY_ROLE_PROFIT = "profit"
CATEGORY_ROLE_BANK = "bank"
CATEGORY_ROLE_SOURCE = "source"
CATEGORY_ROLE_MIRROR = "mirror"
CATEGORY_FOOTER_ROLES = frozenset({"balance", "last_booked"})
CATEGORY_BANK_ROLES = frozenset(
    {CATEGORY_ROLE_BANK, CATEGORY_ROLE_SOURCE, CATEGORY_ROLE_MIRROR}
)
CATEGORY_COMPUTED_ROLES = frozenset({CATEGORY_ROLE_EQUITY, CATEGORY_ROLE_PROFIT})
CATEGORY_HIT_FORBIDDEN_ROLES = frozenset(
    {
        *CATEGORY_COMPUTED_ROLES,
        CATEGORY_ROLE_BANK,
        CATEGORY_ROLE_SOURCE,
        *CATEGORY_FOOTER_ROLES,
    }
)
_ROLE_ALIASES = {
    CATEGORY_ROLE_EQUITY: (CATEGORY_ROLE_EQUITY, "never"),
    "never": (CATEGORY_ROLE_EQUITY, "never"),
    CATEGORY_ROLE_BANK: (CATEGORY_ROLE_BANK, "no_hit"),
    "no_hit": (CATEGORY_ROLE_BANK, "no_hit"),
}


def category_role_text(role: object) -> str:
    return str(role or "").strip().lower()


def category_role_canonical(role: object) -> str:
    """Map stored ``category_role`` to the current name (``never``→``equity``)."""
    text = category_role_text(role)
    if text in (CATEGORY_ROLE_EQUITY, "never"):
        return CATEGORY_ROLE_EQUITY
    if text in (CATEGORY_ROLE_BANK, "no_hit"):
        return CATEGORY_ROLE_BANK
    return text


def is_footer_role(role: object) -> bool:
    return category_role_canonical(role) in CATEGORY_FOOTER_ROLES


def is_remainder_role(role: object) -> bool:
    return category_role_canonical(role) == CATEGORY_ROLE_REMAINDER


def is_equity_role(role: object) -> bool:
    return category_role_canonical(role) == CATEGORY_ROLE_EQUITY


def is_profit_role(role: object) -> bool:
    return category_role_canonical(role) == CATEGORY_ROLE_PROFIT


def is_computed_post_role(role: object) -> bool:
    return category_role_canonical(role) in CATEGORY_COMPUTED_ROLES


def is_hit_forbidden_role(role: object) -> bool:
    return category_role_canonical(role) in CATEGORY_HIT_FORBIDDEN_ROLES


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
    """Leave ``ck_dim_category_role`` alone (no add, no drop).

    ``category_role`` holds system stamps *or* a login username. Schema changes
    to that column are SSMS-only. This only copies leftover ``is_remainder``
    onto ``category_role = remainder`` when that old column still exists.
    """
    cursor.execute(
        "SELECT OBJECT_ID(N'dbo.dim_category', N'U')"
    )
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return
    cursor.execute("SELECT COL_LENGTH(N'dbo.dim_category', N'is_remainder')")
    remainder_col = cursor.fetchone()
    if remainder_col is not None and remainder_col[0] is not None:
        cursor.execute(
            "UPDATE dbo.dim_category SET category_role = N'remainder' "
            "WHERE is_remainder = 1 AND (category_role IS NULL)"
        )


def is_activa(cat_id: int) -> bool:
    """True for 1000-1999, and for local code 1099.

    1099 is the country-5 NL46→NL84 cross-posting. Its category id is 11099
    (local code + 10000); the sheet classifies the local code.
    Passiva and resultaat (3000-4999) share the other class.
    """
    code = int(cat_id)
    return code == 1099 or 1000 <= code <= 1999


def apr_class_sign(cat_id: int) -> int:
    """Journal class sign: A = −1, P = R = +1."""
    return -1 if is_activa(cat_id) else 1


def is_balance_sheet_code(cat_id: int) -> bool:
    """A/P local codes (1000-2999), plus local code 1099.

    Resultaat 3000-4999 stays off the sheet. 1099 is activa: country 5
    stores it as category_id 11099.
    """
    code = int(cat_id)
    return code == 1099 or 1000 <= code <= 2999


def is_resultaat(cat_id: int) -> bool:
    return 3000 <= int(cat_id) <= 4999


def parent_path_segments(path: object) -> list[str]:
    """Split ``dim_category.parent`` (``Activa/Vlottende activa/Kas``) into names."""
    return [seg.strip() for seg in str(path or "").split("/") if seg.strip()]


def category_parents(country_id: int, cursor: object) -> dict[int, str]:
    """local_code → ``dim_category.parent`` path for one country.

    ``parent`` is the slash-separated place of a post in the balance sheet,
    e.g. ``Activa/Vlottende activa/Bank SIa``. Rows with NULL/blank parent
    are omitted; an empty dict when the column does not exist yet.
    """
    cursor.execute("SELECT COL_LENGTH(N'dbo.dim_category', N'parent')")
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return {}
    cursor.execute(
        "SELECT local_code, parent FROM dbo.dim_category "
        "WHERE country_id = ? AND parent IS NOT NULL",
        (int(country_id),),
    )
    out: dict[int, str] = {}
    for local_code, parent in cursor.fetchall():
        if local_code is None:
            continue
        segments = parent_path_segments(parent)
        if segments:
            out[int(local_code)] = "/".join(segments)
    return out


def build_parent_tree(
    posts: list[dict[str, Any]],
    parents: dict[int, str],
    default_root: str | Callable[[dict[str, Any]], str],
) -> list[dict[str, Any]]:
    """Nest ``posts`` under the groups named by their ``parent`` path.

    Each post needs an int ``code`` (local_code), ``label`` and ``amount``.
    A post whose code has no path lands directly under ``default_root``
    (a name, or a callable returning the name for that post). Group names
    match case-insensitively; the first spelling seen is kept. Children of
    every group — posts and sub-groups alike — are ordered by their lowest
    local_code, and each group carries ``total`` (sum of its posts). When
    posts carry ``columns`` (a list of floats, e.g. per-account amounts) every
    group gets ``columns`` with the element-wise sums as well.

    Returns the root groups::

        {"kind": "group", "name": "Activa", "total": 1.0, "children": [
            {"kind": "post", "code": 1000, "label": "Kas Huis", "amount": 1.0},
            {"kind": "group", "name": "Vaste activa", ...},
        ]}
    """
    root: dict[str, Any] = {"kind": "group", "name": "", "children": [], "_index": {}}

    def _group_under(node: dict[str, Any], name: str) -> dict[str, Any]:
        key = name.lower()
        group = node["_index"].get(key)
        if group is None:
            group = {"kind": "group", "name": name, "children": [], "_index": {}}
            node["_index"][key] = group
            node["children"].append(group)
        return group

    for post in posts:
        code = int(post["code"])
        segments = parent_path_segments(parents.get(code))
        if not segments:
            fallback = default_root(post) if callable(default_root) else default_root
            segments = parent_path_segments(fallback) or [str(fallback)]
        node = root
        for segment in segments:
            node = _group_under(node, segment)
        node["children"].append({**post, "kind": "post", "code": code})

    def _finish(node: dict[str, Any]) -> tuple[Decimal, list[Decimal] | None, int | None]:
        total = Decimal("0")
        columns: list[Decimal] | None = None
        first: int | None = None
        for child in node["children"]:
            if child["kind"] == "group":
                child_total, child_columns, child_first = _finish(child)
            else:
                child_total = Decimal(str(child.get("amount") or 0))
                raw_columns = child.get("columns")
                child_columns = (
                    [Decimal(str(value or 0)) for value in raw_columns]
                    if isinstance(raw_columns, list)
                    else None
                )
                child_first = int(child["code"])
            child["_order"] = child_first if child_first is not None else 0
            total += child_total
            if child_columns is not None:
                if columns is None:
                    columns = [Decimal("0")] * len(child_columns)
                for i, value in enumerate(child_columns):
                    if i < len(columns):
                        columns[i] += value
                    else:
                        columns.append(value)
            if child_first is not None and (first is None or child_first < first):
                first = child_first
        node["children"].sort(key=lambda child: child["_order"])
        for child in node["children"]:
            child.pop("_order", None)
        node.pop("_index", None)
        node["total"] = float(total)
        if columns is not None:
            node["columns"] = [float(value) for value in columns]
        return total, columns, first

    _finish(root)
    return root["children"]


def recorded_resultaat_totals(
    country_id: int,
    year: int,
    cursor: object,
) -> dict[int, Decimal]:
    """category_id → SUM of consolidated ``dbo.category_total`` for P&L.

    Every person in every center of the country is included. P&L is
    ``dim_category.local_code`` 3000–4999. Filtering ``category_id`` in that
    range is correct for Beheer (ids = local codes) and empty for Instudo
    (ids are 10000 + local_code, e.g. 13001 for 3001).
    """
    cursor.execute(
        """
        SELECT ct.category_id, SUM(CAST(ct.amount AS decimal(19, 2)))
        FROM dbo.category_total ct
        JOIN dbo.person p ON p.id = ct.person_id
        JOIN dbo.center c ON c.center_id = p.center_id
        JOIN dbo.dim_category d
          ON d.category_id = ct.category_id
         AND d.country_id = c.country_id
        WHERE c.country_id = ?
          AND ct.year = ?
          AND ct.bank_id IS NULL
          AND d.local_code BETWEEN 3000 AND 4999
        GROUP BY ct.category_id
        """,
        (int(country_id), int(year)),
    )
    return {
        int(category_id): _decimal(amount)
        for category_id, amount in cursor.fetchall()
        if category_id is not None
    }


def _spaar_pair(
    source: dict[str, int], mirror: dict[str, int]
) -> dict[str, object]:
    center_id = source.get("center_id")
    if center_id is None:
        center_id = mirror.get("center_id")
    center = str(source.get("center") or mirror.get("center") or "").strip()
    out: dict[str, object] = {
        "source_category": int(source["category_id"]),
        "target_category": int(mirror["category_id"]),
        "source_account_id": int(source["account_id"]),
        "keyword": SPAAR_KEYWORD,
        "center": center,
    }
    if center_id is not None:
        out["center_id"] = int(center_id)
    return out


def _pair_spaar_mirrors(
    sources: list[dict[str, int]],
    mirrors: list[dict[str, int]],
    term_links: list[dict[str, int]],
) -> list[dict[str, object]]:
    """Match each source to the mirror in the same center. Never cross centers."""
    if not sources or not mirrors:
        return []
    if len(sources) == 1 and len(mirrors) == 1:
        return [_spaar_pair(sources[0], mirrors[0])]

    for mirror in mirrors:
        if mirror.get("center_id") is not None:
            continue
        centers = {
            int(link["center_id"])
            for link in term_links
            if int(link["mirror_id"]) == int(mirror["category_id"])
            and link.get("center_id") is not None
        }
        if len(centers) == 1:
            mirror["center_id"] = next(iter(centers))
            names = {
                str(link.get("center") or "").strip()
                for link in term_links
                if int(link["mirror_id"]) == int(mirror["category_id"])
                and str(link.get("center") or "").strip()
            }
            if len(names) == 1:
                mirror["center"] = names.pop()

    used_src: set[int] = set()
    used_mir: set[int] = set()
    pairs: list[dict[str, object]] = []
    by_account: dict[int, list[int]] = {}
    for link in term_links:
        by_account.setdefault(int(link["account_id"]), []).append(int(link["mirror_id"]))

    def _same_center(source: dict[str, int], mirror: dict[str, int]) -> bool:
        src = source.get("center_id")
        dst = mirror.get("center_id")
        if src is None or dst is None:
            return True
        return int(src) == int(dst)

    def _take(
        source: dict[str, int],
        candidates: list[dict[str, int]],
        *,
        require_center: bool = True,
    ) -> bool:
        unique = [
            item
            for item in candidates
            if int(item["category_id"]) not in used_mir
            and (not require_center or _same_center(source, item))
        ]
        if len(unique) != 1:
            return False
        pairs.append(_spaar_pair(source, unique[0]))
        used_src.add(int(source["category_id"]))
        used_mir.add(int(unique[0]["category_id"]))
        return True

    for source in sources:
        wanted = set(by_account.get(int(source["account_id"]), []))
        _take(
            source,
            [item for item in mirrors if int(item["category_id"]) in wanted],
            require_center=False,
        )
    for source in sources:
        if int(source["category_id"]) in used_src:
            continue
        center_id = source.get("center_id")
        if center_id is None:
            continue
        _take(
            source,
            [
                item
                for item in mirrors
                if item.get("center_id") is not None
                and int(item["center_id"]) == int(center_id)
            ],
        )
    for source in sources:
        if int(source["category_id"]) in used_src:
            continue
        center_id = source.get("center_id")
        if center_id is None:
            continue
        scores: dict[int, int] = {}
        for link in term_links:
            if link.get("center_id") is None or int(link["center_id"]) != int(center_id):
                continue
            mid = int(link["mirror_id"])
            scores[mid] = scores.get(mid, 0) + 1
        if not scores:
            continue
        best = max(scores.values())
        winners = [mid for mid, score in scores.items() if score == best]
        if len(winners) != 1:
            continue
        _take(
            source,
            [item for item in mirrors if int(item["category_id"]) == winners[0]],
        )
    return pairs


def spaar_mirrors(
    country_id: int, cursor: object | None = None
) -> list[dict[str, object]]:
    """Every complete source→mirror pair for a country.

    A country may have several (Instudo: one spaarrekening per center). Each
    ``source`` needs ``dbo.mapping_banks.account_id``. A source is paired only
    with the mirror in the same center (mapping leftover or a spaarrekening
    term that lives only in that center). Leftovers are not zipped.
    """
    if cursor is None:
        return []
    cursor.execute(
        """
        SELECT d.category_id, d.local_code, d.category_role, m.account_id,
               p.center_id, n.username
        FROM dbo.dim_category d
        LEFT JOIN dbo.mapping_banks m
          ON m.category_id = d.category_id AND m.country_id = d.country_id
        LEFT JOIN dbo.account a ON a.account_id = m.account_id
        LEFT JOIN dbo.person p ON p.id = a.person_id
        LEFT JOIN dbo.center n ON n.center_id = p.center_id
        WHERE d.country_id = ?
          AND d.category_role IN (N'source', N'mirror')
        """,
        (int(country_id),),
    )
    sources: list[dict[str, int]] = []
    mirrors: list[dict[str, int]] = []
    for row in cursor.fetchall():
        if not row or row[0] is None:
            continue
        category_id = int(row[0])
        center_name = ""
        if len(row) >= 5:
            local_raw, role, account_id, center_id = row[1], row[2], row[3], row[4]
            if len(row) >= 6:
                center_name = str(row[5] or "").strip()
            try:
                local_code = int(local_raw) if local_raw is not None else category_id
            except (TypeError, ValueError):
                local_code = category_id
        else:
            role, account_id = row[1], row[2]
            local_code = category_id
            center_id = None
        text = category_role_text(role)
        item: dict[str, int] = {
            "category_id": category_id,
            "local_code": local_code,
        }
        if center_id is not None:
            item["center_id"] = int(center_id)
        if center_name:
            item["center"] = center_name  # type: ignore[assignment]
        if text == CATEGORY_ROLE_SOURCE:
            if account_id is None:
                continue
            item["account_id"] = int(account_id)
            sources.append(item)
        elif text == CATEGORY_ROLE_MIRROR:
            mirrors.append(item)

    term_links: list[dict[str, int]] = []
    try:
        cursor.execute(
            """
            SELECT t.account_id, d.category_id, p.center_id, n.username
            FROM dbo.category_term t
            JOIN dbo.dim_category d ON d.category_id = t.category_id
            LEFT JOIN dbo.account a ON a.account_id = t.account_id
            LEFT JOIN dbo.person p ON p.id = a.person_id
            LEFT JOIN dbo.center n ON n.center_id = p.center_id
            WHERE d.country_id = ?
              AND d.category_role = N'mirror'
              AND LOWER(t.term) LIKE ?
            """,
            (int(country_id), f"%{SPAAR_KEYWORD}%"),
        )
        for account_id, mirror_id, center_id, center_name in cursor.fetchall():
            if account_id is None or mirror_id is None:
                continue
            link = {"account_id": int(account_id), "mirror_id": int(mirror_id)}
            if center_id is not None:
                link["center_id"] = int(center_id)
            if center_name:
                link["center"] = str(center_name).strip()  # type: ignore[assignment]
            term_links.append(link)
    except Exception:
        term_links = []
    return _pair_spaar_mirrors(sources, mirrors, term_links)


def spaar_mirror(
    country_id: int, cursor: object | None = None
) -> dict[str, object] | None:
    """First spaar pair (sdog / single-center countries)."""
    pairs = spaar_mirrors(country_id, cursor)
    return pairs[0] if pairs else None


def spaar_mirror_target(
    country_id: int, cursor: object | None = None
) -> int | None:
    mirror = spaar_mirror(country_id, cursor)
    return int(mirror["target_category"]) if mirror else None


def spaar_mirror_targets(
    country_id: int, cursor: object | None = None
) -> set[int]:
    return {int(pair["target_category"]) for pair in spaar_mirrors(country_id, cursor)}


def spaar_mirror_posted_amount(source_bank_amount: Decimal) -> Decimal:
    """Mirror counterpart of a source-account spaar row.

    Source amount d is the live source-account bank sign (out negative). The
    mirror posts ``-d`` as stored, not through the activa booking sign: money
    leaving the source (d = -X, X > 0) increases the mirror by X, so plug
    2000 is unchanged.
    """
    return -source_bank_amount


def rebuild_spaar_mirror_rows(
    country_id: int, year: int, cursor: object
) -> int:
    """Replace generated ``dbo.transaction_mirror`` rows for every spaar pair.

    Each source-account keyword row becomes one stored counterpart on that
    pair's mirror category. Returns the number of inserted rows.
    """
    pairs = spaar_mirrors(country_id, cursor)
    if not pairs:
        return 0
    targets = [int(pair["target_category"]) for pair in pairs]
    placeholders = ",".join("?" * len(targets))
    cursor.execute(
        f"""
        DELETE FROM dbo.transaction_mirror
        WHERE year = ? AND country_id = ? AND category_id IN ({placeholders})
          AND description LIKE ? ESCAPE '!'
        """,
        [int(year), int(country_id), *targets, "![" + SPAAR_MARKER[1:] + "%"],
    )
    table = transaction_table(country_id, cursor)
    if table is None:
        return 0
    generated = 0
    for pair in pairs:
        cursor.execute(
            f"SELECT booked_on, amount, description FROM {table} "
            "WHERE year = ? AND account_id = ? "
            "AND LOWER(COALESCE(description, N'')) LIKE ? "
            "ORDER BY booked_on",
            (
                int(year),
                int(pair["source_account_id"]),
                f"%{pair['keyword']}%",
            ),
        )
        rows = list(cursor.fetchall())
        for booked_on, amount, description in rows:
            cursor.execute(
                """
                INSERT INTO dbo.transaction_mirror
                    (year, country_id, date, category_id, amount, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, SYSUTCDATETIME())
                """,
                (
                    int(year),
                    int(country_id),
                    booked_on,
                    int(pair["target_category"]),
                    spaar_mirror_posted_amount(_decimal(amount)),
                    f"{SPAAR_MARKER} {str(description or '')[:180]}",
                ),
            )
            generated += 1
    return generated


def spaar_source_exclude_clause(
    country_id: int, alias: str = "t", *, cursor: object | None = None
) -> tuple[str, list[object]]:
    """SQL that drops source-account spaar-transfer rows (counterpart = mirror).

    ``alias`` is the table alias in the caller (``t`` by default). Use ``""``
    when the FROM table has no alias. Every source account in the country
    is excluded (Instudo has one per center).
    """
    pairs = spaar_mirrors(country_id, cursor)
    if not pairs:
        return "", []
    col = f"{alias}." if alias else ""
    parts: list[str] = []
    params: list[object] = []
    for pair in pairs:
        parts.append(
            f"({col}account_id = ? AND "
            f"LOWER(COALESCE({col}description, N'')) LIKE ?)"
        )
        params.extend([int(pair["source_account_id"]), f"%{pair['keyword']}%"])
    return f" AND NOT ({' OR '.join(parts)})", params


def journal_deltas(
    cat_from: int, cat_to: int, amount: Decimal
) -> tuple[Decimal, Decimal]:
    """Signed (FROM, TO) effect for a hand journal of signed amount ``X``.

    TO always ``+= +X``. FROM takes the **negative** APR product of the two
    class signs (A = −1, P = R = +1): same class ``+= -X``, cross class
    ``+= +X``.
    """
    x = amount
    src_delta = -apr_class_sign(cat_from) * apr_class_sign(cat_to) * x
    dst_delta = x
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
) -> Decimal | None:
    """Overlay for a bank booking of signed amount ``X`` on ``local_code``.

    Transfer from stored category totals (bank sign X) onto the balance
    sheet follows the APR table: A 1000-1999 (except live-bank / spaar)
    ``+= -X``; P 2000-2999 ``+= +X``. Local 1099 and 1100 keep ``+X``.
    The equity post
    (``category_role = equity``) is skipped via its role, not via local_code
    2000. Bank/spaar and computed posts: ``None``.
    """
    code = int(local_code)
    if is_hit_forbidden_role(role):
        return None
    # 1099 (SIa) and 1100 (SIb) keep the statement sign, so the sheet
    # shows the same total as the category: +1000 and −1000 for one wire.
    if code in (1099, 1100):
        return amount
    if 1000 <= code <= 1999:
        return -amount
    if 2000 <= code <= 2999:
        return amount
    return None


def role_category_row(
    country_id: int, role: str, cursor: object
) -> tuple[int, int] | None:
    """``(category_id, local_code)`` for this country's ``category_role``, if any."""
    wanted = category_role_text(role)
    if not wanted:
        return None
    aliases = _ROLE_ALIASES.get(wanted, (wanted,))
    placeholders = ",".join("?" for _ in aliases)
    cursor.execute(
        f"""
        SELECT TOP (1) category_id, local_code
        FROM dbo.dim_category
        WHERE country_id = ?
          AND LOWER(LTRIM(RTRIM(category_role))) IN ({placeholders})
        ORDER BY local_code, category_id
        """,
        (int(country_id), *aliases),
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


def require_remainder_row(country_id: int, cursor: object) -> tuple[int, int]:
    """``(category_id, local_code)`` for ``category_role = remainder``.

    Raises ``CatalogError`` when the country has no such row.
    """
    found = role_category_row(country_id, CATEGORY_ROLE_REMAINDER, cursor)
    if found is None:
        raise CatalogError(
            "No dim_category row with category_role='remainder' "
            f"for country_id={int(country_id)}"
        )
    return found


def verlies_id(country_id: int, cursor: object | None = None) -> int | None:
    """Passiva resultaat post (``category_role = profit``), or ``None``."""
    if cursor is None:
        return None
    return role_category_id(country_id, CATEGORY_ROLE_PROFIT, cursor)


def eigen_vermogen_id(country_id: int, cursor: object | None = None) -> int | None:
    """Eigen vermogen plug (``category_role = equity``), or ``None``."""
    if cursor is None:
        return None
    return role_category_id(country_id, CATEGORY_ROLE_EQUITY, cursor)


def country_has_balance(country_id: int, cursor: object) -> bool:
    """``dbo.country.has_balance`` for a country (False when the row is missing)."""
    cursor.execute(
        "SELECT has_balance FROM dbo.country WHERE country_id = ?",
        (int(country_id),),
    )
    row = cursor.fetchone()
    return bool(row[0]) if row else False


# Posts that must use dbo.balance_opening even when mapping_banks still
# points at an account. 11019 / 11021 are spaar openings. 11099 / 11100 are
# the SIa/SIb cross-posting posts (local 1099 / 1100); they are not bank accounts.
_OPENING_NOT_ACCOUNT_IDS = frozenset({11019, 11021, 11099, 11100})


def account_links(country_id: int, cursor: object) -> dict[int, int]:
    """category_id → account_id from ``dbo.mapping_banks`` for a country.

    The mapping table records which live bank account feeds each balance
    category (the ``source`` post is the spaar checking account).
    ``11019``, ``11021``, ``11099`` and ``11100`` always use ``dbo.balance_opening``. Mirror-role
    posts never ride a leftover ``mapping_banks`` row as a live account.
    """
    skip = set(_OPENING_NOT_ACCOUNT_IDS)
    skip.update(
        cat_id
        for cat_id, role in category_roles(country_id, cursor).items()
        if category_role_canonical(role) == CATEGORY_ROLE_MIRROR
    )
    cursor.execute(
        "SELECT category_id, account_id FROM dbo.mapping_banks WHERE country_id = ?",
        (int(country_id),),
    )
    return {
        int(category_id): int(account_id)
        for category_id, account_id in cursor.fetchall()
        if category_id is not None
        and account_id is not None
        and int(category_id) not in skip
    }


def _dim_category_ids(country_id: int, cursor: object) -> set[int]:
    cursor.execute(
        "SELECT DISTINCT category_id FROM dbo.dim_category "
        "WHERE country_id = ? AND (local_code = 1099 OR local_code BETWEEN 1000 AND 4999)",
        (int(country_id),),
    )
    return {int(r[0]) for r in cursor.fetchall()}


def category_labels(country_id: int, cursor: object) -> dict[int, str]:
    """category_id → label from dbo.dim_category (balance categories)."""
    cursor.execute(
        "SELECT category_id, label FROM dbo.dim_category "
        "WHERE country_id = ? AND (local_code = 1099 OR local_code BETWEEN 1000 AND 4999)",
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
        "WHERE country_id = ? AND (local_code = 1099 OR local_code BETWEEN 1000 AND 4999)",
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

    Every A/P ``dim_category`` row (local_code 1000-2999) is included; side
    comes from the code range. Resultaat 3000-4999 is not a sheet post.
    ``dbo.mapping_banks`` overrides the account link per category.
    """
    codes = category_local_codes(country_id, cursor)
    result: dict[int, tuple[str, int | None]] = {}
    for cat in _dim_category_ids(country_id, cursor):
        local = codes.get(cat, cat)
        if not is_balance_sheet_code(local):
            continue
        result[cat] = (infer_side(local), None)
    roles = category_roles(country_id, cursor)
    for cat_id, role in roles.items():
        if is_computed_post_role(role):
            result.pop(cat_id, None)
            continue
        local = codes.get(cat_id, cat_id)
        if (
            category_role_canonical(role) in CATEGORY_BANK_ROLES
            and cat_id not in result
            and is_balance_sheet_code(local)
        ):
            result[cat_id] = (infer_side(local), None)
    for cat_id, account_id in account_links(country_id, cursor).items():
        local = codes.get(int(cat_id), int(cat_id))
        if not is_balance_sheet_code(local):
            continue
        side, _ = result.get(int(cat_id), (infer_side(local), None))
        result[int(cat_id)] = (side, int(account_id))
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
        "SELECT o.category_id, o.amount FROM dbo.balance_opening o "
        "JOIN dbo.dim_category d ON d.category_id = o.category_id "
        "WHERE d.country_id = ? AND o.year = ?",
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
    pairs = spaar_mirrors(country_id, cursor)
    table = transaction_table(country_id, cursor)
    if not pairs or table is None:
        return {}
    cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return {}
    accounts = [int(pair["source_account_id"]) for pair in pairs]
    placeholders = ",".join("?" * len(accounts))
    q = (
        f"SELECT t.category_id, SUM(t.amount) FROM {table} t "
        "JOIN dbo.person p ON p.id = t.person_id "
        "JOIN dbo.center n ON n.center_id = p.center_id "
        "WHERE n.country_id = ? AND t.year = ? AND t.bank_id IS NULL "
        f"AND t.account_id IN ({placeholders}) "
        "AND LOWER(COALESCE(t.description, N'')) LIKE ?"
    )
    p: list[object] = [
        int(country_id),
        int(year),
        *accounts,
        f"%{pairs[0]['keyword']}%",
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
    """category_id → stored ``dbo.transaction_mirror`` sum (spaar-mirror as-is).

    Mirror amounts are already ``-d`` from generate time; they are not passed
    through the activa booking sign.
    """
    q = (
        "SELECT category_id, SUM(amount) FROM dbo.transaction_mirror "
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
) -> dict[int, Decimal]:
    """category_id → signed overlay from the country's booking table (1000-2999).

    Consolidated rows only (``bank_id IS NULL``). Amount X is the bank sign
    (in +, out -). Activa 1000-1999 get ``-X``; passiva 2000-2999 get ``+X``.
    Codes with a HIT-forbidden ``category_role`` (live bank, ``source``,
    ``equity``, ``profit``) are skipped. ``mirror`` HIT rows are included.
    Source-account spaar-keyword rows are excluded (their counterpart is the
    mirror post). P&L (3000-4999) stays on the resultaat sheet as ``+X``.
    ``{}`` when the table is missing.
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
        "AND (d.local_code = 1099 OR d.local_code BETWEEN 1000 AND 2999) "
        "AND (d.category_role IS NULL OR d.category_role IN "
        "(N'remainder', N'mirror'))"
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
        )
        if signed is None:
            continue
        result[int(category_id)] = signed
    return result


def _journal_table_exists(cursor: object) -> bool:
    cursor.execute("SELECT OBJECT_ID(N'dbo.journal')")
    return cursor.fetchone()[0] is not None


def _journal_effect(
    country_id: int, year: int, cursor: object, *, as_of: date | None = None
) -> dict[int, Decimal]:
    """category_id → net effect from the hand-edited dbo.journal.

    Amount X: TO ``+= +X``; FROM takes the negative APR product of the two
    class signs (A = −1, P = R = +1). FROM 1052 TO 4050 of 9000 moves +9000
    onto both. With ``as_of`` only rows dated on or before that day are
    included.
    """
    if not _journal_table_exists(cursor):
        return {}
    q = (
        "SELECT j.category_from, j.category_to, j.amount FROM dbo.journal j "
        "JOIN dbo.dim_category d ON d.category_id = j.category_from "
        "WHERE d.country_id = ? AND j.year = ?"
    )
    p: list[object] = [int(country_id), int(year)]
    if as_of is not None:
        q += " AND j.date <= ?"
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
) -> dict[int, tuple[int, str]]:
    """cat_id → (cents, source) for every non-computed balance category.

    Bank categories carry the live ``dbo.account.balance`` (with ``as_of``:
    current minus later movements); non-bank categories carry their opening
    balance. ``dbo.transaction_mirror`` sums, ``dbo.journal`` effects,
    and signed booking rows from ``dbo.transaction_{country}`` (codes 1000-2999,
    activa ``-X`` / passiva ``+X``) are added to non-bank posts. Bank-linked
    posts skip the booking sum so the live account is not counted twice.
    Bookings onto live-bank / spaar roles are ignored. The spaar ``mirror``
    post is always opening + stored ``transaction_mirror`` (already ``-d``),
    never a live account and never the activa booking sign. The computed
    posts (``equity`` / ``profit``) are excluded.
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
    mirror_targets = spaar_mirror_targets(country_id, cursor)
    mapping = category_map(country_id, cursor)
    local_codes = category_local_codes(country_id, cursor)
    opening = _opening_balances(country_id, year, cursor)
    _log.warning(
        "sheet start country=%s year=%s as_of=%s openings=%s mapped=%s",
        country_id,
        year,
        as_of,
        len(opening),
        len(mapping),
    )
    for cat_id in sorted(opening, key=lambda i: local_codes.get(i, i)):
        _log.warning(
            "opening row cat=%s local=%s amount=%s mapped=%s",
            cat_id,
            local_codes.get(cat_id),
            opening[cat_id],
            cat_id in mapping,
        )
    journal = _journal_balances(country_id, year, cursor, as_of=as_of)
    effect = _journal_effect(country_id, year, cursor, as_of=as_of)
    bookings = _booking_balances(country_id, year, cursor, as_of=as_of)
    if as_of is None:
        acct = _account_balances(country_id, cursor)
    else:
        acct = _account_balances_asof(country_id, year, cursor, as_of)

    amounts: dict[int, tuple[int, str]] = {}
    for cat_id in sorted(mapping):
        if cat_id in computed:
            _log.warning(
                "sheet line cat=%s local=%s skipped computed role=%s",
                cat_id,
                local_codes.get(cat_id),
                roles.get(cat_id),
            )
            continue
        side, account_id = mapping[cat_id]
        is_mirror = cat_id in mirror_targets
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
        _log.warning(
            "sheet line cat=%s local=%s account=%s mirror=%s opening=%s "
            "mirror_sum=%s journal=%s bookings=%s final=%s source=%s",
            cat_id,
            local_codes.get(cat_id),
            account_id,
            is_mirror,
            opening.get(cat_id),
            journal.get(cat_id),
            effect.get(cat_id),
            bookings.get(cat_id),
            amount,
            source,
        )
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
    date; ``None`` means the live, full-year values. Same APR signs as the
    balance sheet (A ``-X``).
    """
    return {
        cat: cents
        for cat, (cents, _source) in balance_category_breakdown(
            country_id,
            year,
            cursor,
            as_of=as_of,
        ).items()
    }


def afschrijving_like_pattern() -> str:
    """LIKE pattern for auto depreciation rows (``[`` is a LIKE character class)."""
    return "![" + AFSCHRIJVING_MARKER[1:] + "%"


def afschrijving_amount(fraction: object, present: Decimal) -> Decimal:
    """``fraction * present``, two decimal places."""
    return (Decimal(str(fraction)) * present).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def is_kosten_local(local_code: int) -> bool:
    """True for the 3000-series (kosten), not 4000-series opbrengsten."""
    return 3000 <= int(local_code) <= 3999


def category_transaction_sum(
    country_id: int,
    year: int,
    category_id: int,
    cursor: object,
    *,
    local_code: int | None = None,
) -> Decimal:
    """SUM of booking rows shown when clicking that category in the matrix.

    Same filter as the 1060 drill-down: ``bank_id IS NULL``, ``dim.local_code``
    (so Instudo ``11060`` counts as 1060). Journal and mirror are omitted.
    """
    table = transaction_table(country_id, cursor)
    if table is None:
        return Decimal("0")
    cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return Decimal("0")
    local = int(local_code) if local_code is not None else int(category_id)
    cid = int(country_id)
    y = int(year)
    cursor.execute(
        f"""
        SELECT SUM(CAST(t.amount AS decimal(19, 2)))
        FROM {table} t
        JOIN dbo.person p ON p.id = t.person_id
        JOIN dbo.center n ON n.center_id = p.center_id
        JOIN dbo.dim_category d ON d.category_id = t.category_id
        WHERE n.country_id = ?
          AND t.year = ?
          AND t.bank_id IS NULL
          AND d.local_code = ?
        """,
        (cid, y, local),
    )
    row = cursor.fetchone()
    return _decimal(row[0]) if row and row[0] is not None else Decimal("0")


def is_afschrijving_present_role(role: object) -> bool:
    """True when ``dbo.afschrijvingen.role`` is 1 (present amount of van)."""
    if role is True or role == 1:
        return True
    if isinstance(role, str) and role.strip() in {"1", "true", "True"}:
        return True
    return False


def apply_afschrijvingen(country_id: int, cursor: object) -> int:
    """Replace ``[afschrijving]`` journal rows from ``dbo.afschrijvingen``.

    Existing marker rows are deleted first so the amount is the live sheet
    without last login's depreciation. Then one journal is written per rule
    and year: FROM ``local_code_van`` TO ``local_code_naar``. ``role = 1``
    uses ``fraction * present(van)``. ``role = 0`` uses ``fraction`` times
    the SUM of ``transaction_*`` bookings on van (all persons, that year,
    ``bank_id IS NULL``; no journal or mirror). Empty rules still wipe
    leftover marker rows. ``0`` when the table is missing. Does not commit.
    """
    cursor.execute("SELECT OBJECT_ID(N'dbo.afschrijvingen', N'U')")
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return 0
    if not _journal_table_exists(cursor):
        return 0
    cid = int(country_id)
    cursor.execute(
        "SELECT role, fraction, local_code_van, local_code_naar "
        "FROM dbo.afschrijvingen WHERE country_id = ? ORDER BY id",
        (cid,),
    )
    rules = [r for r in cursor.fetchall() if r is not None]
    years: set[int] = set()
    cursor.execute(
        "SELECT DISTINCT o.year FROM dbo.balance_opening o "
        "JOIN dbo.dim_category d ON d.category_id = o.category_id "
        "WHERE d.country_id = ?",
        (cid,),
    )
    years.update(int(r[0]) for r in cursor.fetchall() if r and r[0] is not None)
    cursor.execute(
        "SELECT DISTINCT j.year FROM dbo.journal j "
        "JOIN dbo.dim_category d ON d.category_id = j.category_from "
        "WHERE d.country_id = ?",
        (cid,),
    )
    years.update(int(r[0]) for r in cursor.fetchall() if r and r[0] is not None)
    table = transaction_table(cid, cursor)
    if table:
        cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
        if cursor.fetchone()[0] is not None:
            cursor.execute(f"SELECT DISTINCT year FROM {table}")
            years.update(
                int(r[0]) for r in cursor.fetchall() if r and r[0] is not None
            )
    if not years:
        return 0
    codes = category_local_codes(cid, cursor)
    local_to_id = {int(local): int(cat) for cat, local in codes.items()}
    like = afschrijving_like_pattern()
    written = 0
    for year in sorted(years):
        cursor.execute(
            "DELETE j FROM dbo.journal j "
            "JOIN dbo.dim_category d ON d.category_id = j.category_from "
            "WHERE d.country_id = ? AND j.year = ? "
            "AND j.description LIKE ? ESCAPE '!'",
            (cid, int(year), like),
        )
        cents = present_balance_cents(cid, int(year), cursor)
        for role, fraction, van, naar in rules:
            try:
                van_local = int(van)
                naar_local = int(naar)
            except (TypeError, ValueError):
                continue
            van_id = local_to_id.get(van_local)
            naar_id = local_to_id.get(naar_local)
            if van_id is None and van_local in codes:
                van_id = van_local
            if naar_id is None and naar_local in codes:
                naar_id = naar_local
            if van_id is None or naar_id is None:
                continue
            use_present = is_afschrijving_present_role(role)
            if use_present:
                present = Decimal(cents.get(van_id, cents.get(van_local, 0))) / Decimal(
                    100
                )
            else:
                present = category_transaction_sum(
                    cid, int(year), van_id, cursor, local_code=van_local
                )
            amount = afschrijving_amount(fraction, present)
            if use_present and amount == 0:
                continue
            kind = (
                "TRUE: huidige balanswaarde"
                if use_present
                else "FALSE: afgeboekte bedragen"
            )
            description = (
                f"{AFSCHRIJVING_MARKER} {kind} [{van_local}] × {fraction}"
            )
            cursor.execute(
                "INSERT INTO dbo.journal "
                "(year, date, category_from, category_to, "
                "amount, description, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, SYSUTCDATETIME())",
                (
                    int(year),
                    f"{int(year)}-12-31",
                    van_id,
                    naar_id,
                    amount,
                    description[:512],
                ),
            )
            written += 1
    return written


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
    ``dbo.transaction_mirror`` add their amount as stored. With ``as_of``
    (YYYY-MM-DD) only rows dated on or before that day are included. Returns
    ``{}`` when either table is missing.
    """
    for table in ("dbo.journal", "dbo.transaction_mirror"):
        cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
        if cursor.fetchone()[0] is None:
            return {}
    journal_date = " AND j.date <= ?" if as_of is not None else ""
    mirror_date = " AND date <= ?" if as_of is not None else ""
    params: list[object] = [int(country_id), int(year)]
    if as_of is not None:
        params.append(as_of)
    overlay: dict[int, int] = {}
    codes = category_local_codes(country_id, cursor)
    cursor.execute(
        "SELECT j.category_from, j.category_to, j.amount FROM dbo.journal j "
        "JOIN dbo.dim_category d ON d.category_id = j.category_from "
        f"WHERE d.country_id = ? AND j.year = ?{journal_date}",
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
        "SELECT category_id, amount FROM dbo.transaction_mirror "
        f"WHERE country_id = ? AND year = ?{mirror_date}",
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