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
    if 1000 <= code <= 1999:
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
#   rc              rekening courant: zeroed into cp by Calculate opening balance
#   sia / sib       rc post that is also the unit leg of a Centrale SIa / SIb pair
#   siasib          SIa leg of a SIa–SIb pair: keeps the statement sign, not zeroed
#   cp              kruisposten: receives the rc total on the opening balance
#   4000            reserved label: an HD login shows kruisposten here
#                   The role is not booked. The HD sheet calculates the line.
CATEGORY_ROLE_REMAINDER = "remainder"
CATEGORY_ROLE_EQUITY = "equity"
CATEGORY_ROLE_PROFIT = "profit"
CATEGORY_ROLE_BANK = "bank"
CATEGORY_ROLE_SOURCE = "source"
CATEGORY_ROLE_MIRROR = "mirror"
CATEGORY_ROLE_RC = "rc"
CATEGORY_ROLE_SIA = "sia"
CATEGORY_ROLE_SIB = "sib"
CATEGORY_ROLE_SIASIB = "siasib"
CATEGORY_ROLE_CP = "cp"
CATEGORY_ROLE_CASH = "cash"
CATEGORY_ROLE_UNIT_PROFIT = "4000"
# HD label for kruisposten. Present in dim_category so the local code stays
# reserved. Bookings and journals do not use it. A work unit does not show it.
UNIT_RESULT_RESERVE_ROLES = frozenset({CATEGORY_ROLE_UNIT_PROFIT})
UNIT_KRUISPOSTEN_LABELS = {
    CATEGORY_ROLE_UNIT_PROFIT: "Inkomsten residentie",
}
KRUISPOSTEN_CASH_LABEL = "Kruisposten"
# Zeroed into cp on the opening balance.
CATEGORY_RC_ROLES = frozenset({CATEGORY_ROLE_RC, CATEGORY_ROLE_SIA, CATEGORY_ROLE_SIB})
# Bookings keep the statement sign. siasib is here and not in CATEGORY_RC_ROLES.
CATEGORY_CROSS_POSTING_ROLES = frozenset(
    {*CATEGORY_RC_ROLES, CATEGORY_ROLE_SIASIB, CATEGORY_ROLE_CP}
)
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
        *UNIT_RESULT_RESERVE_ROLES,
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


def is_rc_role(role: object) -> bool:
    """``rc``, ``sia`` or ``sib``: zeroed into ``cp`` on the opening balance."""
    return category_role_canonical(role) in CATEGORY_RC_ROLES


def is_cp_role(role: object) -> bool:
    return category_role_canonical(role) == CATEGORY_ROLE_CP


def is_cross_posting_role(role: object) -> bool:
    """An rc post, the siasib post or the cp post: bookings keep the statement sign."""
    return category_role_canonical(role) in CATEGORY_CROSS_POSTING_ROLES


def cross_posting_role_sql(column: str) -> str:
    """SQL predicate: ``column`` holds an rc, siasib or cp role (trimmed, any case)."""
    names = ", ".join(f"N'{name}'" for name in sorted(CATEGORY_CROSS_POSTING_ROLES))
    return f"LOWER(LTRIM(RTRIM({column}))) IN ({names})"


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


def is_unit_result_reserve_role(role: object) -> bool:
    """``4000``: a sheet label, not a category that is booked."""
    return category_role_canonical(role) in UNIT_RESULT_RESERVE_ROLES


def is_journal_forbidden_role(role: object) -> bool:
    return is_computed_post_role(role) or is_unit_result_reserve_role(role)


def unit_kruisposten_role(kind: str) -> str | None:
    """Catalog role that receives kruisposten on this login, or ``None``.

    An HD login shows role 4000 (4995, Inkomsten residentie). A work unit
    does not show that line.
    """
    if kind == "hd":
        return CATEGORY_ROLE_UNIT_PROFIT
    return None


def unit_kruisposten_local(kind: str) -> int | None:
    """Local code of the shown kruisposten line: 4995 for an HD login."""
    if kind == "hd":
        return 4995
    return None


def balance_category_id(country_id: int, local_code: int) -> int:
    """``category_id`` for a balance country: ``(country_id - 4) * 10000 + local_code``."""
    return (int(country_id) - 4) * 10000 + int(local_code)


def kruisposten_view_adjustment(
    cp_amount: Decimal, *, kind: str, cp_local: int
) -> tuple[Decimal, Decimal]:
    """Hand journal on a category total already calculated for this view.

    ``cp_amount`` is the cross-posting total the view just summed. For an HD
    login the journal amount is minus that total, van 4995, naar the cp post.
    The shown result line is the opposite of that van-leg, so Inkomsten
    residentie is positive. Returns ``(cp total to show, amount added to the
    result line)``. A work unit and every higher login keep the cp total and
    add nothing.
    """
    van_local = unit_kruisposten_local(kind)
    if van_local is None or cp_amount == 0:
        return cp_amount, Decimal("0")
    _amount, effect_van, effect_cp = implicit_kruisposten_journal(
        van_local, int(cp_local), cp_amount
    )
    return cp_amount + effect_cp, shown_kruisposten_result(kind, effect_van)


def shown_kruisposten_result(kind: str, effect_van: Decimal) -> Decimal:
    """Result-line amount for this login.

    An HD login shows Inkomsten residentie with the opposite sign of the
    van-leg, so that amount is positive. A work unit does not show the line.
    """
    if kind == "hd":
        return -effect_van
    return effect_van


def implicit_kruisposten_journal(
    van_local: int, cp_local: int, cp_statement: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    """Hand journal ``van`` 4995, ``naar`` the cp post.

    The amount is minus the cp total already calculated for this login.
    Nothing is written to ``dbo.journal``. Returns ``(amount, effect on van,
    effect on cp)``.
    """
    amount = -cp_statement
    effect_van, effect_cp = journal_deltas(int(van_local), int(cp_local), amount)
    return amount, effect_van, effect_cp


def split_kruisposten_extra(
    extras: list[tuple[str, Decimal]],
) -> tuple[list[tuple[str, Decimal]], Decimal]:
    """Take the Kruisposten line off the cash extras and return its amount."""
    kept: list[tuple[str, Decimal]] = []
    amount = Decimal("0")
    for label, value in extras:
        if label == KRUISPOSTEN_CASH_LABEL:
            amount += value
        else:
            kept.append((label, value))
    return kept, amount


def cash_inkomsten_uitgaven(
    kind: str,
    kosten_sum: Decimal,
    opbrengsten_sum: Decimal,
    kruis: Decimal,
    column_effect: Decimal = Decimal("0"),
) -> tuple[Decimal, Decimal]:
    """Cash-table Uitgaven and Inkomsten.

    An HD login already includes ``column_effect``, Inkomsten residentie, in
    the profit column. Kruisposten ``kruis`` has been removed from the
    extras, so the cash line puts that statement total back on Inkomsten
    and negates the profit column first. A work unit keeps the resultaat
    totals: 4995 is not on that sheet, and the cash table settles the same
    amount on Rekening courant instead.
    """
    if kind == "hd":
        plain = opbrengsten_sum - column_effect
        return kosten_sum, -plain + kruis
    return kosten_sum, opbrengsten_sum


def place_unit_kruisposten_row(
    rows: list[dict[str, Any]],
    total_months: list[Decimal],
    *,
    code: int,
    label: str,
    months: list[Decimal],
) -> None:
    """Insert the calculated kruisposten line and add it to the sheet total.

    A year that sums to zero is still inserted when a month is non-zero, so
    Overige mutaties loses exactly those months.
    """
    shown = list(months)
    if not any(part != 0 for part in shown):
        return
    for index, part in enumerate(shown):
        if index < len(total_months):
            total_months[index] += part
    row = {
        "code": int(code),
        "label": label,
        "months": [float(part) for part in shown],
        "amount": float(sum(shown, Decimal("0"))),
    }
    for index, existing in enumerate(rows):
        if int(existing.get("code") or 0) > int(code):
            rows.insert(index, row)
            return
    rows.append(row)


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
    if is_footer_role(role) or is_unit_result_reserve_role(role):
        return text
    if code is None or code == "":
        return None
    return f"{int(code):04d} {text}"


def ensure_category_role_booking_rules(cursor: object) -> None:
    """Leave ``dbo.dim_category`` alone.

    ``category_role`` holds system stamps or a login username. Remainder is
    that role, not a separate column. Schema changes stay in SSMS.
    """
    del cursor


def is_activa(cat_id: int) -> bool:
    """True for local codes 1000-1999.

    Passiva and resultaat (3000-4999) share the other class.
    """
    code = int(cat_id)
    return 1000 <= code <= 1999


def apr_class_sign(cat_id: int) -> int:
    """Journal class sign: A = −1, P = R = +1."""
    return -1 if is_activa(cat_id) else 1


def is_balance_sheet_code(cat_id: int) -> bool:
    """A/P local codes (1000-2999). Resultaat 3000-4999 stays off the sheet."""
    code = int(cat_id)
    return 1000 <= code <= 2999


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
    pair's mirror category. The booking that caused the row is categorized
    as that mirror category. Rows already at modification 1, 2, 3, or 4
    keep their category. Returns the number of inserted rows.
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
        target = int(pair["target_category"])
        cursor.execute(
            f"""
            UPDATE {table}
            SET category_id = ?
            WHERE year = ? AND account_id = ?
              AND LOWER(COALESCE(description, N'')) LIKE ?
              AND modification IN (-1, 0)
            """,
            (
                target,
                int(year),
                int(pair["source_account_id"]),
                f"%{pair['keyword']}%",
            ),
        )
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
    ``+= -X``; P 2000-2999 ``+= +X``. ``category_role`` ``rc`` and ``cp``
    keep the statement sign ``+X``, whichever local code they sit on.
    The equity post (``category_role = equity``) is skipped via its role,
    not via local_code 2000. Bank/spaar and computed posts: ``None``.
    """
    code = int(local_code)
    if is_hit_forbidden_role(role):
        return None
    # rc/cp keep the statement sign. The local code does not: 1112–1119 are
    # ordinary activa unless this row's category_role is rc, sia, sib,
    # siasib or cp.
    if is_cross_posting_role(role):
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
# points at an account. 11019 / 11021 are spaar openings. 11100 is the
# SIa leg of the SIa/SIb cross-posting (local 1100); it is not a bank account.
_OPENING_NOT_ACCOUNT_IDS = frozenset({11019, 11021, 11100})

# Instudo HD cash on hand. mapping_banks still names the account, but the
# sheet must not copy that account's balance. The post is the opening row
# (zero when dbo.balance_opening has none) plus Geldautomaat bookings.
CASH_ON_HAND_BANK_TYPE = "Geldautomaat"
CASH_ON_HAND_ACCOUNT: dict[int, int] = {
    11133: 55,
    11134: 48,
    11135: 57,
    11136: 47,
    11137: 46,
    11138: 45,
    11139: 56,
}


def cash_category_accounts(country_id: int, cursor: object) -> dict[int, int]:
    """category_id → account_id for each HD account's own cash post.

    An account is HD when ``mapping_banks`` points it at ``category_role``
    ``hd``. Its cash post is the ``cash`` category mapped to that same
    account. A ``Geldautomaat`` booking on the account is stored on that
    cash post. The sheet does not copy the account balance onto it.
    Country 5 keeps the known 11133–11139 pairs when those role rows are
    not readable yet.
    """
    cursor.execute(
        """
        SELECT cash.category_id, m_cash.account_id
        FROM dbo.mapping_banks m_hd
        JOIN dbo.dim_category hd
          ON hd.category_id = m_hd.category_id AND hd.country_id = m_hd.country_id
        JOIN dbo.mapping_banks m_cash
          ON m_cash.account_id = m_hd.account_id
         AND m_cash.country_id = m_hd.country_id
        JOIN dbo.dim_category cash
          ON cash.category_id = m_cash.category_id
         AND cash.country_id = m_cash.country_id
        WHERE m_hd.country_id = ?
          AND LOWER(LTRIM(RTRIM(ISNULL(hd.category_role, N'')))) = N'hd'
          AND LOWER(LTRIM(RTRIM(ISNULL(cash.category_role, N'')))) = N'cash'
        """,
        (int(country_id),),
    )
    by_account: dict[int, int] = {}
    for category_id, account_id in cursor.fetchall():
        if category_id is None or account_id is None:
            continue
        account = int(account_id)
        category = int(category_id)
        previous = by_account.get(account)
        if previous is None or category < previous:
            by_account[account] = category
    if by_account:
        return {category: account for account, category in by_account.items()}
    if int(country_id) == 5:
        return dict(CASH_ON_HAND_ACCOUNT)
    return {}


def account_links(country_id: int, cursor: object) -> dict[int, int]:
    """category_id → account_id from ``dbo.mapping_banks`` for a country.

    The mapping table records which live bank account feeds each balance
    category (the ``source`` post is the spaar checking account).
    ``11019``, ``11021`` and ``11100`` always use ``dbo.balance_opening``. Mirror-role
    posts never ride a leftover ``mapping_banks`` row as a live account.
    A ``cash`` post is opening plus the bookings stored on that category,
    not the mapped account's balance.
    """
    skip = set(_OPENING_NOT_ACCOUNT_IDS)
    skip.update(CASH_ON_HAND_ACCOUNT)
    skip.update(cash_category_accounts(country_id, cursor))
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


def category_visibility(country_id: int, cursor: object) -> dict[int, int] | None:
    """category_id → ``dim_category.visibility`` (1–5).

    ``None`` when the column is not on this database yet.
    """
    cursor.execute("SELECT COL_LENGTH(N'dbo.dim_category', N'visibility')")
    row = cursor.fetchone()
    if not row or row[0] is None:
        return None
    cursor.execute(
        "SELECT category_id, visibility FROM dbo.dim_category WHERE country_id = ?",
        (int(country_id),),
    )
    from shared.user_access import normalize_visibility

    return {
        int(item[0]): normalize_visibility(item[1])
        for item in cursor.fetchall()
        if item[0] is not None
    }


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


def _money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def opening_amounts_from_year_end(
    year_end: dict[int, tuple[int, str]],
    opening_prev: dict[int, Decimal],
    roles: dict[int, str],
    local_codes: dict[int, int],
    equity_id: int,
    result_sum: Decimal,
    *,
    include_live_banks: bool = False,
) -> dict[int, Decimal]:
    """Opening amounts for year Y from the year-end sheet of Y−1.

    Each stored non-bank post becomes that year-end amount. Live bank posts
    (source ``account:``) are included only when ``include_live_banks`` is set,
    which is how an existing year is overwritten. ``category_role=profit``
    is a 2000-range post. ``category_role=balance`` is a 3000-range post
    whose amount is ``result_sum``: the numerical sum of local codes
    3000–4999 except that balance post. Profit is set to zero and
    ``result_sum`` is added to the previous year's Eigen vermogen opening
    (``category_role=equity``). Every category with ``category_role=rc``
    is set to zero, and their total is added to ``category_role=cp``
    (local 1200 when that row is present),     so the activa total is unchanged.
    """
    profit_ids = {
        cat_id
        for cat_id, role in roles.items()
        if category_role_canonical(role) == "profit"
        and 2000 <= local_codes.get(cat_id, cat_id) <= 2999
    }
    balance_ids = {
        cat_id
        for cat_id, role in roles.items()
        if category_role_canonical(role) == "balance"
        and is_resultaat(local_codes.get(cat_id, cat_id))
    }
    if not profit_ids:
        raise CatalogError("No 2000-category with category_role=profit")
    if not balance_ids:
        raise CatalogError("No 3000-category with category_role=balance")
    written: dict[int, Decimal] = {}
    for cat_id, (cents, source) in year_end.items():
        if cat_id in profit_ids:
            continue
        if str(source).startswith("account:") and not include_live_banks:
            continue
        written[cat_id] = _money(Decimal(int(cents)) / Decimal(100))
    for cat_id in profit_ids:
        written[cat_id] = Decimal("0.00")
    written[int(equity_id)] = _money(
        opening_prev.get(int(equity_id), 0) + _money(result_sum)
    )

    rc_ids = {
        cat_id
        for cat_id, role in roles.items()
        if is_rc_role(role)
    }
    cp_id = _cp_category_id(roles, local_codes)
    if rc_ids and cp_id is None:
        raise CatalogError("No category with category_role=cp")

    def assigned(cat_id: int) -> Decimal:
        if cat_id in written:
            return written[cat_id]
        found = year_end.get(cat_id)
        if found is not None:
            cents, source = found
            if not (str(source).startswith("account:") and not include_live_banks):
                return _money(Decimal(int(cents)) / Decimal(100))
        return _money(opening_prev.get(cat_id, 0))

    if rc_ids and cp_id is not None:
        rc_total = Decimal("0.00")
        for cat_id in sorted(rc_ids, key=lambda i: (local_codes.get(i, i), i)):
            amount = assigned(cat_id)
            rc_total += amount
            written[cat_id] = Decimal("0.00")
        written[cp_id] = _money(assigned(cp_id) + rc_total)
    return written


def _cp_category_id(roles: dict[int, str], local_codes: dict[int, int]) -> int | None:
    """``category_role=cp``, preferring local code 1200."""
    found = [
        cat_id
        for cat_id, role in roles.items()
        if is_cp_role(role)
    ]
    if not found:
        return None
    for cat_id in found:
        if local_codes.get(cat_id, cat_id) == 1200:
            return cat_id
    return min(found, key=lambda cat_id: (local_codes.get(cat_id, cat_id), cat_id))


def _opening_year_count(country_id: int, year: int, cursor: object) -> int:
    cursor.execute(
        "SELECT COUNT(*) FROM dbo.balance_opening o "
        "JOIN dbo.dim_category d ON d.category_id = o.category_id "
        "WHERE d.country_id = ? AND o.year = ?",
        (int(country_id), int(year)),
    )
    row = cursor.fetchone()
    return int(row[0] or 0) if row else 0


def _copy_opening_year(
    country_id: int, source_year: int, target_year: int, cursor: object
) -> None:
    cursor.execute(
        "INSERT INTO dbo.balance_opening (category_id, year, amount) "
        "SELECT o.category_id, ?, o.amount "
        "FROM dbo.balance_opening o "
        "JOIN dbo.dim_category d ON d.category_id = o.category_id "
        "WHERE d.country_id = ? AND o.year = ?",
        (int(target_year), int(country_id), int(source_year)),
    )


def _upsert_opening_amount(
    category_id: int, year: int, amount: Decimal, cursor: object
) -> None:
    cursor.execute(
        """
        IF EXISTS (SELECT 1 FROM dbo.balance_opening
                   WHERE category_id = ? AND year = ?)
            UPDATE dbo.balance_opening
            SET amount = ?
            WHERE category_id = ? AND year = ?
        ELSE
            INSERT INTO dbo.balance_opening (category_id, year, amount)
            VALUES (?, ?, ?)
        """,
        int(category_id),
        int(year),
        amount,
        int(category_id),
        int(year),
        int(category_id),
        int(year),
        amount,
    )


def _resultaat_sum(
    country_id: int,
    year: int,
    cursor: object,
    exclude_ids: set[int],
) -> Decimal:
    """Numerical sum of local codes 3000–4999, excluding ``exclude_ids``.

    Bookings use the same rows as the sheet result (spaar-source rows left
    out). Journal and spaar-mirror effects on those categories are added.
    """
    total = Decimal("0")
    table = transaction_table(country_id, cursor)
    if table:
        cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
        row = cursor.fetchone()
        if row is not None and row[0] is not None:
            exclude_sql, exclude_params = spaar_source_exclude_clause(
                country_id, cursor=cursor
            )
            skip = ""
            skip_params: list[object] = []
            if exclude_ids:
                marks = ",".join("?" * len(exclude_ids))
                skip = f" AND t.category_id NOT IN ({marks})"
                skip_params = [int(cat_id) for cat_id in exclude_ids]
            cursor.execute(
                f"SELECT COALESCE(SUM(t.amount), 0) FROM {table} t "
                "JOIN dbo.dim_category d ON d.category_id = t.category_id "
                "AND d.country_id = ? "
                "WHERE t.year = ? "
                "AND d.local_code BETWEEN 3000 AND 4999"
                f"{skip}{exclude_sql}",
                (int(country_id), int(year), *skip_params, *exclude_params),
            )
            got = cursor.fetchone()
            if got is not None and got[0] is not None:
                total += _decimal(got[0])
    for cat_id, cents in result_overlay_cents(country_id, year, cursor).items():
        if int(cat_id) in exclude_ids:
            continue
        total += Decimal(int(cents)) / Decimal(100)
    return _money(total)


_CREDITOR_LOCAL = 2500


def creditor_label(raw: object) -> str:
    """Lowercase simplified name for ``dbo.subadministratie`` (max 64)."""
    text = re.sub(r"[^\w\s]", " ", str(raw or "").casefold(), flags=re.UNICODE)
    return " ".join(text.replace("_", " ").split())[:64]


def _booking_person_name(counterparty: object, description: object) -> str:
    party = str(counterparty or "").strip()
    if party:
        return party
    text = str(description or "").strip()
    _, _, rest = text.partition("Naam:")
    if rest:
        name = rest.split("Omschrijving:", 1)[0].strip()
        if name:
            return name
    return text


def roll_creditor_amounts(
    previous: list[tuple[int, str, Decimal]],
    movements: list[tuple[int, str, Decimal]],
) -> list[tuple[int, str, Decimal]]:
    """Opening creditors: previous sub-ledger plus that year's bookings.

    Names are the lowercase simplified form. A zero balance is left out.
    """
    totals: dict[tuple[int, str], Decimal] = {}
    for local_code, name, amount in [*previous, *movements]:
        label = creditor_label(name)
        if not label:
            continue
        key = (int(local_code), label)
        totals[key] = totals.get(key, Decimal("0")) + _money(amount)
    return [
        (local_code, label, _money(amount))
        for (local_code, label), amount in sorted(totals.items())
        if amount != 0
    ]


def subadministratie_year_present(cursor: object) -> bool:
    """Whether ``dbo.subadministratie.year`` is present.

    ``False`` when the table itself is absent. Raises ``CatalogError`` when
    the table is present and ``year`` is not.
    """
    cursor.execute("SELECT OBJECT_ID(N'dbo.subadministratie', N'U')")
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return False
    cursor.execute("SELECT COL_LENGTH(N'dbo.subadministratie', N'year')")
    col = cursor.fetchone()
    if col is None or col[0] is None:
        raise CatalogError("dbo.subadministratie has no year column")
    return True


def _write_opening_creditors(country_id: int, year: int, cursor: object) -> int:
    """Replace year Y's creditor rows from Y−1's sub-ledger and bookings.

    Private creditors are local code 2500, plus any other local code already
    stored for this country. Does nothing when the table is missing. Stops
    when the table has no ``year`` column.
    """
    if not subadministratie_year_present(cursor):
        return 0
    target = int(year)
    previous = target - 1
    cid = int(country_id)
    cursor.execute(
        "SELECT COUNT(*) FROM dbo.subadministratie WHERE country_id = ? AND year = ?",
        (cid, previous),
    )
    counted = cursor.fetchone()
    if not counted or not counted[0]:
        cursor.execute(
            "UPDATE dbo.subadministratie SET year = ? "
            "WHERE country_id = ? AND year IS NULL",
            (previous, cid),
        )
    cursor.execute(
        "SELECT local_code, name, amount FROM dbo.subadministratie "
        "WHERE country_id = ? AND year = ?",
        (cid, previous),
    )
    previous_rows = [
        (int(code), str(name or ""), _decimal(amount))
        for code, name, amount in cursor.fetchall()
        if code is not None
    ]
    codes = {_CREDITOR_LOCAL}
    cursor.execute(
        "SELECT DISTINCT local_code FROM dbo.subadministratie WHERE country_id = ?",
        (cid,),
    )
    codes.update(int(code) for (code,) in cursor.fetchall() if code is not None)
    marks = ",".join("?" for _ in codes)
    cursor.execute(
        f"SELECT local_code FROM dbo.dim_category "
        f"WHERE country_id = ? AND local_code IN ({marks})",
        (cid, *sorted(codes)),
    )
    allowed = {int(code) for (code,) in cursor.fetchall() if code is not None}
    movements: list[tuple[int, str, Decimal]] = []
    table = transaction_table(cid, cursor)
    if table and allowed:
        cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
        present = cursor.fetchone()
        if present is not None and present[0] is not None:
            code_marks = ",".join("?" for _ in allowed)
            cursor.execute(
                f"SELECT d.local_code, t.counterparty_name, t.description, t.amount "
                f"FROM {table} t "
                "JOIN dbo.dim_category d ON d.category_id = t.category_id "
                "AND d.country_id = ? "
                "WHERE t.year = ? AND t.bank_id IS NULL "
                f"AND d.local_code IN ({code_marks})",
                (cid, previous, *sorted(allowed)),
            )
            for local_code, party, description, amount in cursor.fetchall():
                if local_code is None:
                    continue
                movements.append((
                    int(local_code),
                    _booking_person_name(party, description),
                    _decimal(amount),
                ))
    rows = [
        (code, label, amount)
        for code, label, amount in roll_creditor_amounts(previous_rows, movements)
        if code in allowed
    ]
    cursor.execute(
        "DELETE FROM dbo.subadministratie WHERE country_id = ? AND year = ?",
        (cid, target),
    )
    for local_code, label, amount in rows:
        cursor.execute(
            "INSERT INTO dbo.subadministratie "
            "(country_id, local_code, name, amount, year) VALUES (?, ?, ?, ?, ?)",
            (cid, int(local_code), label, amount, target),
        )
    return len(rows)


def is_opening_sheet_year(country_id: int, year: int, cursor: object) -> bool:
    """True when ``year`` is the stored opening after the latest booking year."""
    target = int(year)
    if _opening_year_count(country_id, target, cursor) == 0:
        return False
    table = transaction_table(country_id, cursor)
    if table is None:
        return False
    cursor.execute(f"SELECT OBJECT_ID(N'{table}', N'U')")
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return False
    cursor.execute(
        f"SELECT MAX(t.year) FROM {table} t "
        "JOIN dbo.person p ON p.id = t.person_id "
        "JOIN dbo.center n ON n.center_id = p.center_id "
        "WHERE n.country_id = ?",
        (int(country_id),),
    )
    found = cursor.fetchone()
    latest = None if found is None or found[0] is None else int(found[0])
    return latest is not None and target == latest + 1


def opening_sheet_breakdown(
    country_id: int, year: int, cursor: object
) -> dict[int, tuple[int, str]] | None:
    """Closed openings for ``year``, in balance-sheet cents.

    Same figures Calculate opening balance would write: every ``rc``, ``sia``
    and ``sib`` category is zero, and their year-end total is on ``cp``.
    Does not write. ``None`` when the close cannot run.
    """
    target = int(year)
    previous = target - 1
    if _opening_year_count(country_id, previous, cursor) == 0:
        return None
    equity_id = eigen_vermogen_id(country_id, cursor)
    if equity_id is None:
        return None
    roles = category_roles(country_id, cursor)
    codes = category_local_codes(country_id, cursor)
    balance_ids = {
        cat_id
        for cat_id, role in roles.items()
        if category_role_canonical(role) == "balance"
        and is_resultaat(codes.get(cat_id, cat_id))
    }
    try:
        amounts = opening_amounts_from_year_end(
            balance_category_breakdown(
                country_id, previous, cursor, trace=False
            ),
            _opening_balances(country_id, previous, cursor),
            roles,
            codes,
            int(equity_id),
            _resultaat_sum(country_id, previous, cursor, balance_ids),
            include_live_banks=_opening_year_count(country_id, target, cursor) > 0,
        )
    except CatalogError:
        return None
    return {
        int(cat_id): (_to_cents(amount), "opening")
        for cat_id, amount in amounts.items()
    }


def calculate_opening_balance(country_id: int, year: int, cursor: object) -> dict[str, Any]:
    """Write year Y's opening balances from year Y−1. Does not commit.

    When Y has no ``dbo.balance_opening`` rows, every row of Y−1 for this
    country is copied first. Y−1 must already have rows. When Y already has
    rows, those amounts are overwritten, including live bank posts. The
    figures come from :func:`opening_amounts_from_year_end`.
    """
    target = int(year)
    previous = target - 1
    exists = _opening_year_count(country_id, target, cursor) > 0
    if _opening_year_count(country_id, previous, cursor) == 0:
        raise CatalogError(f"No opening balance for {previous}")
    if not exists:
        _copy_opening_year(country_id, previous, target, cursor)
    apply_afschrijvingen(country_id, cursor)
    equity_id = eigen_vermogen_id(country_id, cursor)
    if equity_id is None:
        raise CatalogError(
            f"No category with category_role=equity for country_id={int(country_id)}"
        )
    roles = category_roles(country_id, cursor)
    codes = category_local_codes(country_id, cursor)
    balance_ids = {
        cat_id
        for cat_id, role in roles.items()
        if category_role_canonical(role) == "balance"
        and is_resultaat(codes.get(cat_id, cat_id))
    }
    amounts = opening_amounts_from_year_end(
        balance_category_breakdown(country_id, previous, cursor),
        _opening_balances(country_id, previous, cursor),
        roles,
        codes,
        int(equity_id),
        _resultaat_sum(country_id, previous, cursor, balance_ids),
        include_live_banks=exists,
    )
    for cat_id, amount in amounts.items():
        _upsert_opening_amount(cat_id, target, amount, cursor)
    creditors = _write_opening_creditors(country_id, target, cursor)
    return {
        "ok": True,
        "year": target,
        "country_id": int(country_id),
        "copied": not exists,
        "updated": len(amounts),
        "equity": str(amounts[int(equity_id)]),
        "creditors": creditors,
    }


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
    ``equity``, ``profit``) are skipped. ``mirror``, ``cp`` and ``rc`` HIT
    rows are included.
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
        "AND d.local_code BETWEEN 1000 AND 2999 "
        "AND (d.category_role IS NULL "
        "OR LOWER(LTRIM(RTRIM(d.category_role))) IN (N'remainder', N'mirror') "
        f"OR {cross_posting_role_sql('d.category_role')})"
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
    included. A closed year's afschrijving is booked on 31 December of that
    year. The year under way is booked on the day the calculation runs.
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
        p.append(as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of))
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
    trace: bool = True,
) -> dict[int, tuple[int, str]]:
    """cat_id → (cents, source) for every non-computed balance category.

    Bank categories carry the live ``dbo.account.balance`` (with ``as_of``:
    current minus later movements); non-bank categories carry their opening
    balance. ``dbo.transaction_mirror`` sums, ``dbo.journal`` effects,
    and signed booking rows from ``dbo.transaction_{country}`` (codes 1000-2999,
    activa ``-X`` / passiva ``+X``) are added to non-bank posts. Bank-linked
    posts skip the booking sum so the live account is not counted twice.
    Instudo cash posts 11133–11139 are not live accounts: opening plus the
    bookings stored on that category.
    Bookings onto live-bank / spaar roles are ignored. The spaar ``mirror``
    post is always opening + stored ``transaction_mirror`` (already ``-d``),
    never a live account and never the activa booking sign. The computed
    posts (``equity`` / ``profit``) are excluded.
    """
    def _sheet_log(message: str, *args: object) -> None:
        if trace:
            _log.warning(message, *args)

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
    _sheet_log(
        "sheet start country=%s year=%s as_of=%s openings=%s mapped=%s",
        country_id,
        year,
        as_of,
        len(opening),
        len(mapping),
    )
    for cat_id in sorted(opening, key=lambda i: local_codes.get(i, i)):
        _sheet_log(
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
            _sheet_log(
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
        _sheet_log(
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


def afschrijving_booked_on(year: int, *, on: date | None = None) -> str:
    """Book date for one year's afschrijving journals.

    The year under way is the day the calculation runs. A run on 15 January
    2027 for 2027 books 2027-01-15. Every other year is 31 December of that
    year, so the same run for 2026 books 2026-12-31.
    """
    day = on or date.today()
    booked_year = int(year)
    if booked_year == day.year:
        return day.isoformat()
    return f"{booked_year:04d}-12-31"


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
    and year: FROM ``category_id_van`` TO ``category_id_naar``. ``role = 1``
    uses ``fraction * present(van)``. ``role = 0`` uses ``fraction`` times
    the SUM of ``transaction_*`` bookings on van (all persons, that year,
    ``bank_id IS NULL``; no journal or mirror). Empty rules still wipe
    leftover marker rows. The year under way is booked on the day of the
    run. Every other year is booked on 31 December of that year.
    ``0`` when the table is missing. Does not commit.
    """
    cursor.execute("SELECT OBJECT_ID(N'dbo.afschrijvingen', N'U')")
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return 0
    if not _journal_table_exists(cursor):
        return 0
    cid = int(country_id)
    cursor.execute(
        "SELECT a.role, a.fraction, "
        "dv.category_id, dv.local_code, dn.category_id, dn.local_code "
        "FROM dbo.afschrijvingen a "
        "JOIN dbo.dim_category dv ON dv.category_id = a.category_id_van "
        "JOIN dbo.dim_category dn ON dn.category_id = a.category_id_naar "
        "WHERE dv.country_id = ? AND dn.country_id = ? "
        "ORDER BY a.id",
        (cid, cid),
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
        for role, fraction, van_id, van_local, naar_id, naar_local in rules:
            try:
                van_id = int(van_id)
                naar_id = int(naar_id)
                van_local = int(van_local)
                naar_local = int(naar_local)
            except (TypeError, ValueError):
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
                    afschrijving_booked_on(year),
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
    (YYYY-MM-DD) only rows dated on or before that day are included.
    A closed year's afschrijving journals are booked on 31 December of that
    year. Returns ``{}`` when either table is missing.
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