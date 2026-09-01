from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import runtime as paths

DEFAULT_CATEGORY = 18
CATEGORIZE_LOGIC_VERSION = "2026-08-26-ircft-personal-and-last-stick"
_TERM_AND_SEP = " && "
_ACCOUNT_INDEX_FIELD = "_account_index"


def _use_sql() -> bool:
    from app import user_store

    return bool(user_store.database_url())


def _under_data_root(path: Path) -> bool:
    from app.runtime import data_root

    try:
        path.resolve().relative_to(data_root().resolve())
        return True
    except (ValueError, OSError):
        return False


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_json_object(path: Path) -> dict[str, Any]:
    if _use_sql() and _under_data_root(path):
        return {}
    if not path.exists():
        return {}
    try:
        data = _read_json(path)
    except (OSError, json.JSONDecodeError, FileNotFoundError):
        return {}
    return data if isinstance(data, dict) else {}


def _sql_categories() -> dict[str, Any]:
    from app.runtime import active_center, active_country
    from app.sql_catalog import categories_payload, country_for_center

    country = active_country() or country_for_center(active_center() or "") or ""
    return categories_payload(country)


def _personal_category_map() -> dict[str, list[str]]:
    if _use_sql():
        from app.sql_catalog import personal_categories_payload

        name = str(paths.BOUND_PERSON or paths.PERSON_NAME or "").strip()
        return personal_categories_payload(name)
    data = _load_json_object(paths.PERSONAL_CATEGORIES_PATH)
    return _category_map(data)


def _load_categorized_store() -> dict[str, Any]:
    """Bookings for the bound person/year(/bank): SQL when configured, else JSON."""
    from app.sql_replica import load_bound_transactions

    if _use_sql():
        rows = load_bound_transactions()
        return {"transactions": [dict(item) for item in (rows or [])]}
    rows = load_bound_transactions()
    if rows is not None:
        return {"transactions": [dict(item) for item in rows]}
    return _migrate_categorized_store(_load_json_object(paths.CATEGORIZED_TRANSACTIONS_PATH))


def _persist_categorized_store(data: dict[str, Any]) -> dict[str, Any]:
    """UPDATE matching SQL rows."""
    data = _migrate_categorized_store(data)
    data.pop("modifications", None)
    from app.sql_replica import sync_bound_transactions

    txs = data.get("transactions")
    if isinstance(txs, list):
        sync_bound_transactions(txs)
    return data


def _category_map(data: dict[str, Any]) -> dict[str, list[str]]:
    nested = data.get("categories")
    return nested if isinstance(nested, dict) else data


def _amount(transaction: dict[str, Any]) -> str:
    amount = str((transaction.get("transaction_amount") or {}).get("amount", "")).strip()
    sign = "+" if transaction.get("credit_debit_indicator") == "CRDT" else "-"
    return f"{sign}{amount}" if amount else ""


def _currency(transaction: dict[str, Any]) -> str:
    return str((transaction.get("transaction_amount") or {}).get("currency", "")).strip()


def _type(transaction: dict[str, Any]) -> str:
    return str((transaction.get("bank_transaction_code") or {}).get("description") or "").strip()


_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)


def _is_date_or_datetime(value: str) -> bool:
    value = value.strip()
    return bool(_DATE_ONLY.fullmatch(value) or _DATETIME.fullmatch(value))


def _parse_brace_key_values(block: str) -> dict[str, str]:
    inner = block.strip()
    if inner.startswith("{"):
        inner = inner[1:].lstrip()
    if inner.endswith("}"):
        inner = inner[:-1].rstrip()
    pairs: dict[str, str] = {}
    for part in inner.split(","):
        if ":" not in part:
            continue
        key, _, value = part.partition(":")
        key = key.strip()
        value = value.strip()
        if key:
            pairs[key] = value
    return pairs


def _format_brace_key_values(pairs: dict[str, str]) -> str:
    if not pairs:
        return ""
    inner = " , ".join(f"{key} : {value}" for key, value in pairs.items())
    return f"{{ {inner} }}"


def _split_bracketed_remittance(lines: list[str]) -> tuple[str, str] | None:
    if not lines:
        return None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            prefix = " ".join(
                part.strip() for i, part in enumerate(lines) if i != index and part.strip()
            )
            return prefix, stripped
    if len(lines) == 1:
        match = re.match(r"^(.*?)(\{[^{}]*\})\s*$", lines[0], re.DOTALL)
        if match:
            return match.group(1).strip(), match.group(2).strip()
    return None


def _remittance_iban_from_lines(lines: list[str]) -> str:
    for line in lines:
        if ":" in line:
            prefix, value = line.split(":", 1)
            if prefix.strip() == "IBAN":
                return value.strip()
    return ""


def _pop_brace_key(pairs: dict[str, str], key_name: str) -> str:
    target = key_name.lower()
    for key in list(pairs):
        if key.lower() == target:
            return pairs.pop(key)
    return ""


def _remittance_lines(transaction: dict[str, Any]) -> list[str]:
    raw = transaction.get("remittance_information") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(line).strip() for line in raw if line]


def _structured_remittance_fields(transaction: dict[str, Any]) -> dict[str, str]:
    lines = _remittance_lines(transaction)
    split = _split_bracketed_remittance(lines)
    bank_type = _type(transaction)
    iban_from_lines = _remittance_iban_from_lines(lines)
    tx_id = transaction.get("entry_reference") or transaction.get("id")

    if split is None:
        result = {
            "type": bank_type,
            "iban": iban_from_lines,
            "description": " ".join(lines),
        }
        # _debug_remittance_log(
        #     {
        #         "fn": "_structured_remittance_fields",
        #         "tx_id": tx_id,
        #         "lines": lines,
        #         "split": None,
        #         "bank_type": bank_type,
        #         "iban_from_lines": iban_from_lines,
        #         "result": result,
        #     }
        # )
        return result

    prefix, block = split
    pairs = _parse_brace_key_values(block)
    pairs_raw = dict(pairs)

    tx_type = _pop_brace_key(pairs, "TransactionSubType")
    iban = _pop_brace_key(pairs, "MandateId")
    pairs_after_extract = dict(pairs)
    pairs = {key: value for key, value in pairs.items() if not _is_date_or_datetime(value)}
    pairs_after_date_filter = dict(pairs)

    remainder = _format_brace_key_values(pairs)
    if prefix and remainder:
        description = f"{prefix} {remainder}"
    elif remainder:
        description = remainder
    else:
        description = prefix

    result = {
        "type": tx_type or bank_type,
        "iban": iban or iban_from_lines,
        "description": description,
    }
    return result


def _naam(transaction: dict[str, Any]) -> str:
    party_key = "creditor" if transaction.get("credit_debit_indicator") == "DBIT" else "debtor"
    party = transaction.get(party_key) or {}
    return str(party.get("name") or "").strip()


def _booking_date(transaction: dict[str, Any]) -> str:
    raw = str(transaction.get("booking_date") or "").strip()
    parts = raw.split("-")
    if len(parts) == 3:
        year, month, day = parts
        return f"{day}-{month}-{year}"
    return raw


_CATEGORY_CODE = re.compile(r"^(\d{2,4})(?=\D|$)")


def _category_code(name: str) -> int | None:
    match = _CATEGORY_CODE.match(str(name).strip())
    if not match:
        return None
    return int(match.group(1))


# Letters, dots, and ``*`` (common in merchant names like ``BCK*Praxis229``).
_HASH_WILDCARD = "[a-z.*]*"


def _term_body_pattern(term: str) -> str:
    """Regex body for a keyword; each ``#`` matches zero or more letters, dots, or ``*``."""
    parts: list[str] = []
    for ch in term:
        if ch == "#":
            if not parts or parts[-1] != _HASH_WILDCARD:
                parts.append(_HASH_WILDCARD)
        else:
            parts.append(re.escape(ch))
    return "".join(parts)


def _letters_only(word: str) -> str:
    """Keep letters, dots, and ``*``; strip digits/punctuation for hash matching."""
    return re.sub(r"[^a-z.*]", "", word.lower())


def _matches_hash_word(term: str, haystack: str) -> bool:
    body = _term_body_pattern(term)
    pattern = re.compile(body)
    for token in haystack.lower().split():
        for candidate in {token, _letters_only(token)}:
            if candidate and pattern.fullmatch(candidate):
                return True
    return False


def _matches_phrase(term: str, haystack: str) -> bool:
    """Match one phrase (no `` && ``) against the haystack."""
    if "#" not in term:
        return re.search(rf"\b{re.escape(term)}\b", haystack) is not None

    if " " in term:
        body = _term_body_pattern(term)
        return re.search(rf"\b{body}\b", haystack) is not None

    return _matches_hash_word(term, haystack)


def _matches_and_group(group: str, haystack: str) -> bool:
    if _TERM_AND_SEP in group:
        return all(
            _matches_phrase(part.strip(), haystack)
            for part in group.split(_TERM_AND_SEP)
            if part.strip()
        )
    return _matches_phrase(group, haystack)


def _matches_word(field: str, haystack: str) -> bool:
    term = field.lower().strip()
    if not term:
        return False
    return _matches_and_group(term, haystack)


def _haystack_for_categorization(record: dict[str, Any]) -> str:
    """Keyword haystack from processed remittance fields (name + description only)."""
    if _remittance_lines(record):
        remittance = _structured_remittance_fields(record)
        name = _naam(record)
        description = remittance["description"]
    else:
        name = str(record.get("name") or "")
        description = str(record.get("description") or "")
    return f"{name} {description}".lower()


def _categories_file() -> dict[str, Any]:
    if _use_sql():
        return _sql_categories()
    path = paths.CATEGORIES_PATH
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
        except (OSError, json.JSONDecodeError, UnicodeError):
            pass
    return _sql_categories()


def type_rules_payload() -> list[dict[str, str]]:
    """Validated ``typerules`` from ``categories.json`` (for API / UI legend)."""
    raw = _categories_file().get("typerules")
    if not isinstance(raw, list):
        return []
    rules: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rule_type = str(item.get("type") or "").strip()
        category_name = str(item.get("category") or "").strip()
        if not rule_type or not category_name:
            continue
        if _category_code(category_name) is None:
            continue
        rules.append({"type": rule_type, "category": category_name})
    return rules


def _type_rule_category_map() -> dict[str, int]:
    """Map lowercased bank ``type`` strings to category codes."""
    mapping: dict[str, int] = {}
    for rule in type_rules_payload():
        code = _category_code(rule["category"])
        if code is not None:
            mapping[rule["type"].lower()] = code
    return mapping


def _category_from_type_rules(record: dict[str, Any]) -> int | None:
    tx_type = _transaction_type_for_categorization(record).lower()
    if not tx_type:
        return None
    return _type_rule_category_map().get(tx_type)


def _transaction_type_for_categorization(record: dict[str, Any]) -> str:
    if _remittance_lines(record):
        return _structured_remittance_fields(record)["type"]
    return str(record.get("type") or "")


HIT_PERSONAL_PREFIX = "P:"
HIT_GENERAL_PREFIX = "G:"


def format_hit(term: str, *, personal: bool) -> str:
    prefix = HIT_PERSONAL_PREFIX if personal else HIT_GENERAL_PREFIX
    return f"{prefix}{term}"


def parse_hit(hit: Any) -> tuple[bool, str] | None:
    text = str(hit or "").strip()
    if text.startswith(HIT_PERSONAL_PREFIX):
        return True, text[len(HIT_PERSONAL_PREFIX) :]
    if text.startswith(HIT_GENERAL_PREFIX):
        return False, text[len(HIT_GENERAL_PREFIX) :]
    return None


def _priority_key(term: str, *, personal: bool, category_name: str) -> tuple:
    """Higher wins: personal, then ``&&``, then category-alphabetical last-stick."""
    return (
        1 if personal else 0,
        1 if _TERM_AND_SEP in term else 0,
        category_name,
        term,
    )


def _name_by_code(general: dict[str, list[str]]) -> dict[int, str]:
    return {
        code: name
        for name in general
        if (code := _category_code(name)) is not None
    }


def _existing_priority_key(
    record: dict[str, Any], name_by_code: dict[int, str]
) -> tuple | None:
    parsed = parse_hit(record.get("hit"))
    if parsed is None:
        return None
    personal, term = parsed
    code = _as_category_code(record.get("category"))
    category_name = name_by_code.get(code, "") if code is not None else ""
    return _priority_key(term, personal=personal, category_name=category_name)


def _best_keyword_hit(
    haystack: str,
    general: dict[str, list[str]],
    personal: dict[str, list[str]],
) -> tuple[int, str] | None:
    best_key: tuple | None = None
    best: tuple[int, str] | None = None
    for is_personal, group in ((False, general), (True, personal)):
        for name, fields in group.items():
            code = _category_code(name)
            if code is None:
                continue
            for field in fields or []:
                term = str(field).lower().strip()
                if not term or not _matches_word(term, haystack):
                    continue
                key = _priority_key(term, personal=is_personal, category_name=name)
                if best_key is None or key > best_key:
                    best_key = key
                    best = (code, format_hit(term, personal=is_personal))
    return best


def categorize_with_hit(
    record: dict[str, Any],
    general: dict[str, list[str]],
    personal: dict[str, list[str]],
) -> tuple[int, str | None]:
    type_match = _category_from_type_rules(record)
    if type_match is not None:
        return type_match, None
    haystack = _haystack_for_categorization(record)
    keyword_match = _best_keyword_hit(haystack, general, personal)
    if keyword_match is not None:
        return keyword_match
    return DEFAULT_CATEGORY, None


def categorize(
    record: dict[str, Any],
    general: dict[str, list[str]],
    personal: dict[str, list[str]],
) -> int:
    code, _hit = categorize_with_hit(record, general, personal)
    return code


def _account_index(transaction: dict[str, Any]) -> int:
    raw = transaction.get(_ACCOUNT_INDEX_FIELD, 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _categorized_transaction_id(transaction: dict[str, Any]) -> str:
    ref = transaction.get("entry_reference")
    if ref is not None and str(ref).strip():
        return f"{str(ref).strip()}_{_account_index(transaction)}"
    tid = transaction.get("id")
    return str(tid).strip() if tid is not None else ""


def _tx_sort_key(transaction: Any) -> int:
    tid = transaction.get("id") if isinstance(transaction, dict) else None
    text = str(tid) if tid is not None else ""
    if "_" in text:
        base, suffix = text.rsplit("_", 1)
        if suffix.isdigit():
            text = base
    return int(text) if text.isdigit() else -1


def simplify_transaction(transaction: dict[str, Any]) -> dict[str, Any]:
    remittance = _structured_remittance_fields(transaction)
    return {
        "id": _categorized_transaction_id(transaction),
        "amount": _amount(transaction),
        "currency": _currency(transaction),
        "type": remittance["type"],
        "name": _naam(transaction),
        "iban": remittance["iban"],
        "description": remittance["description"],
        "date": _booking_date(transaction),
    }


MOD_UNCALCULATED = -1
MOD_NONE = 0
MOD_CATEGORY = 1
MOD_DESCRIPTION = 2
MOD_BOTH = 3
MOD_CATEGORY_BIT = 1
MOD_DESCRIPTION_BIT = 2

_MODIFICATION_FIELDS = frozenset({"category", "description"})


def _as_category_code(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _modification_of(transaction: dict[str, Any]) -> int:
    raw = transaction.get("modification")
    if raw is None:
        return MOD_UNCALCULATED if transaction.get("category") is None else MOD_NONE
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return MOD_NONE
    if value < MOD_UNCALCULATED or value > MOD_BOTH:
        return MOD_NONE
    return value


def _user_set_category(flag: int) -> bool:
    return flag >= 0 and bool(flag & MOD_CATEGORY_BIT)


def _with_mod_bits(current: int, *, category: bool = False, description: bool = False) -> int:
    value = MOD_NONE if current < 0 else current
    if category:
        value |= MOD_CATEGORY_BIT
    if description:
        value |= MOD_DESCRIPTION_BIT
    return value


def _canonical_transaction(transaction: dict[str, Any]) -> dict[str, Any]:
    record = dict(transaction)
    legacy_iban = record.pop("IBAN", None)
    if legacy_iban is not None and not record.get("iban"):
        record["iban"] = legacy_iban
    record.pop("category_locked", None)
    record["modification"] = _modification_of(record)
    return record


def _modifications_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    modifications = payload.get("modifications")
    if not isinstance(modifications, list):
        return {}
    by_id: dict[str, dict[str, Any]] = {}
    for item in modifications:
        if isinstance(item, dict) and item.get("id") is not None:
            by_id[str(item.get("id"))] = item
    return by_id


def _effective_transaction(
    base: dict[str, Any],
    mods_by_id: dict[str, dict[str, Any]] | None = None,
    *,
    modification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Row values are the effective ones; leftover ``modifications[]`` still overlay once."""
    effective = _canonical_transaction(base)
    mod = modification
    if mod is None and mods_by_id is not None and base.get("id") is not None:
        mod = mods_by_id.get(str(base.get("id")))
    if not isinstance(mod, dict):
        return effective
    for key in _MODIFICATION_FIELDS:
        if key in mod:
            effective[key] = mod[key]
    return effective


def _values_equal(key: str, left: Any, right: Any) -> bool:
    if key == "category":
        a = _as_category_code(left)
        b = _as_category_code(right)
        if a is not None and b is not None:
            return a == b
    return str(left if left is not None else "") == str(right if right is not None else "")


def _migrate_modifications(data: dict[str, Any]) -> dict[str, Any]:
    """Fold legacy ``modifications[]`` onto each row; store ``modification`` -1..3."""
    mods_by_id = _modifications_by_id(data)
    rows = data.get("transactions")
    if isinstance(rows, list):
        for item in rows:
            if not isinstance(item, dict):
                continue
            item.pop("category_locked", None)
            overlay = mods_by_id.get(str(item.get("id"))) if item.get("id") is not None else None
            cat_changed = isinstance(overlay, dict) and "category" in overlay
            desc_changed = isinstance(overlay, dict) and "description" in overlay
            if cat_changed:
                item["category"] = overlay["category"]
            if desc_changed:
                item["description"] = overlay["description"]
            flag = _modification_of(item)
            if cat_changed or desc_changed:
                item["modification"] = _with_mod_bits(
                    flag if flag >= 0 else MOD_NONE,
                    category=cat_changed,
                    description=desc_changed,
                )
            else:
                item["modification"] = flag
    data.pop("modifications", None)
    return data


def _migrate_categorized_store(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("transactions")
    if isinstance(items, list):
        data["transactions"] = [
            _canonical_transaction(item) if isinstance(item, dict) else item for item in items
        ]
    return _migrate_modifications(data)


def _merge_simplified(existing: dict[str, Any], new_records: list[dict[str, Any]]) -> dict[str, Any]:
    existing_tx = existing.get("transactions")
    existing_tx = existing_tx if isinstance(existing_tx, list) else []
    by_id: dict[Any, dict[str, Any]] = {
        item.get("id"): _canonical_transaction(item)
        for item in existing_tx
        if isinstance(item, dict) and item.get("id") is not None
    }
    for record in new_records:
        record_id = record.get("id")
        if record_id is None or record_id in by_id:
            continue
        by_id[record_id] = _canonical_transaction(record)
    merged = sorted(by_id.values(), key=_tx_sort_key, reverse=True)

    result = dict(existing)
    result["transactions"] = merged
    return result


_SIMPLIFIED_FIELDS = ("amount", "currency", "type", "name", "iban", "description", "date")


def _fill_transaction_fields(
    record: dict[str, Any], simplified: dict[str, Any]
) -> dict[str, Any]:
    """Copy distilled bank fields onto a stored transaction (does not set category)."""
    filled = dict(record)
    for field in _SIMPLIFIED_FIELDS:
        if field in simplified:
            filled[field] = simplified[field]
    return filled


def _is_excel_row(transaction: dict[str, Any]) -> bool:
    """True when the transaction was imported from an Excel (.xlsx) sheet.

    Excel rows carry ``type == "Excel"`` (see ``excel_import.rows_to_transactions``)
    and their category is authoritative from the user's sheet, so categorization
    must not re-run the keyword matcher over them.
    """
    return str(transaction.get("type") or "").strip() == "Excel"


def _categorize_transactions(
    records: list[dict[str, Any]],
    general: dict[str, list[str]],
    personal: dict[str, list[str]],
    *,
    match_sources: dict[Any, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    categorized: list[dict[str, Any]] = []
    for record in records:
        updated = dict(record)
        updated.pop("category_locked", None)
        source = record
        if match_sources is not None:
            source = match_sources.get(record.get("id"), record)
        flag = _modification_of(updated)
        if not _user_set_category(flag) and not _is_excel_row(source):
            code, hit = categorize_with_hit(source, general, personal)
            updated["category"] = code
            updated["hit"] = hit
            if flag == MOD_UNCALCULATED:
                updated["modification"] = MOD_NONE
        categorized.append(updated)
    return categorized


def _simplify_uncategorized(raw_transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Distill bank JSON without running keyword matching."""
    rows: list[dict[str, Any]] = []
    for transaction in raw_transactions:
        record = simplify_transaction(transaction)
        record["category"] = DEFAULT_CATEGORY
        record["hit"] = None
        record["modification"] = MOD_UNCALCULATED
        rows.append(record)
    return rows


def finalize_imported_bookings(*, recategorize: bool = True) -> dict[str, str]:
    """INSERT bound JSON bookings as uncategorized, then categorize them."""
    from app.sql_replica import ensure_bound_accounts, ingest_bound_transactions

    totals = _load_json_object(paths.CATEGORY_TOTALS_PATH)
    accounts = totals.get("account_balances")
    if isinstance(accounts, list) and accounts:
        ensure_bound_accounts(accounts, default_format=None)
    rows = _load_json_object(paths.CATEGORIZED_TRANSACTIONS_PATH).get("transactions") or []
    if isinstance(rows, list):
        ingest_bound_transactions(rows)
    if recategorize:
        return recategorize_transactions()
    return {}


def _amount_to_cents(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return round(float(text) * 100)
    except ValueError:
        return 0


def _amount_str(cents: int) -> str:
    return f"{cents / 100:.2f}"


def build_category_totals(
    transactions_payload: dict[str, Any], general_names: list[str]
) -> dict[str, str]:
    """Per-category signed totals from the category stored on each row."""
    name_by_code = {
        code: name for name in general_names if (code := _category_code(name)) is not None
    }
    booking_names = [name for name in general_names if _category_code(name) is not None]
    totals: dict[str, int] = {name: 0 for name in booking_names}
    data = _migrate_categorized_store(
        {
            "transactions": [
                dict(item)
                for item in (transactions_payload.get("transactions") or [])
                if isinstance(item, dict)
            ],
            "modifications": list(transactions_payload["modifications"])
            if isinstance(transactions_payload.get("modifications"), list)
            else [],
        }
    )
    for transaction in data.get("transactions", []):
        if not isinstance(transaction, dict):
            continue
        effective = _canonical_transaction(transaction)
        code = _as_category_code(effective.get("category"))
        name = name_by_code.get(code, str(code)) if code is not None else str(effective.get("category"))
        totals[name] = totals.get(name, 0) + _amount_to_cents(effective.get("amount"))

    return {name: _amount_str(cents) for name, cents in totals.items()}


def _write_category_totals(merged: dict[str, Any], general: dict[str, list[str]]) -> dict[str, str]:
    return build_category_totals(merged, list(general.keys()))


def refresh_category_totals_balances() -> dict[str, str]:
    """Recompute category totals (no recategorization, no files written)."""
    general = _category_map(_categories_file())
    merged = _load_categorized_store()
    categories = build_category_totals(merged, list(general.keys()))
    return {str(name): str(amount) for name, amount in categories.items()}


def load_category_totals() -> dict[str, str]:
    from app.sql_replica import load_bound_transactions

    if _use_sql():
        from app.sql_replica import load_bound_category_totals

        general = _category_map(_categories_file())
        names = list(general.keys())
        totals = load_bound_category_totals(names)
        if totals is not None:
            return totals
        rows = load_bound_transactions() or []
        return build_category_totals({"transactions": rows}, names)
    rows = load_bound_transactions()
    if rows is not None:
        general = _category_map(_categories_file())
        return build_category_totals({"transactions": rows}, list(general.keys()))
    data = _load_json_object(paths.CATEGORY_TOTALS_PATH)
    categories = data.get("categories")
    if not isinstance(categories, dict):
        return {}
    return {str(name): str(amount) for name, amount in categories.items()}


def _load_raw_transactions() -> list[dict[str, Any]]:
    if _use_sql():
        return []
    if not paths.RAW_TRANSACTIONS_PATH.exists():
        return []
    try:
        raw = _read_json(paths.RAW_TRANSACTIONS_PATH)
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        items = raw.get("transactions")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _raw_bank_by_id() -> dict[Any, dict[str, Any]]:
    by_id: dict[Any, dict[str, Any]] = {}
    for raw in _load_raw_transactions():
        record_id = _categorized_transaction_id(raw)
        if record_id:
            by_id[record_id] = raw
    return by_id


def _raw_simplified_by_id() -> dict[Any, dict[str, Any]]:
    by_id: dict[Any, dict[str, Any]] = {}
    for raw in _load_raw_transactions():
        record = simplify_transaction(raw)
        record_id = record.get("id")
        if record_id is not None:
            by_id[record_id] = record
    return by_id


def recategorize_transactions(*, from_scratch: bool = False) -> dict[str, str]:
    """Re-categorize rows that the user has not locked with a category edit.

    ``modification`` 1 or 3 keeps ``category``.  -1 becomes 0 after the first
    calculation. Description stays on the row (already overwritten if M is 2/3).

    ``from_scratch`` clears ``hit`` and sets ``modification`` to -1 first, so
    every row is treated as uncalculated (user category/description locks
    are dropped). The algorithm then fills ``category``, ``hit``, and sets
    ``modification`` to 0.
    """
    general = _category_map(_categories_file())
    personal = _personal_category_map()
    data = _load_categorized_store()

    existing_tx = data.get("transactions")
    existing_tx = existing_tx if isinstance(existing_tx, list) else []
    records = [
        _canonical_transaction(item)
        for item in existing_tx
        if isinstance(item, dict) and item.get("id") is not None
    ]
    if from_scratch:
        for record in records:
            record["hit"] = None
            record["modification"] = MOD_UNCALCULATED

    categorized = _categorize_transactions(records, general, personal)

    result = dict(data) if data else {}
    result["transactions"] = sorted(categorized, key=_tx_sort_key, reverse=True)
    result.pop("modifications", None)

    result = _persist_categorized_store(result)
    return _write_category_totals(result, general)


def ircft_add_term(
    term: str,
    *,
    personal: bool,
    category_name: str,
    general: dict[str, list[str]],
    personal_map: dict[str, list[str]],
) -> bool:
    """Apply one newly added term without recategorizing every row.

    Call after the term is already saved. Unlocked rows with no ``hit`` are
    backfilled with a full categorize (the new term is already in the maps).
    Rows that already have a hit are updated only when the new term matches
    and outranks the stored hit.
    """
    normalized = _normalize_term(term)
    if not normalized:
        return False
    new_key = _priority_key(normalized, personal=personal, category_name=category_name)
    new_hit = format_hit(normalized, personal=personal)
    name_by_code = _name_by_code(general)
    new_code = _category_code(category_name)

    payload = _load_categorized_store()
    transactions = payload.get("transactions")
    if not isinstance(transactions, list) or new_code is None:
        return False

    changed = False
    next_rows: list[dict[str, Any]] = []
    for transaction in transactions:
        if not isinstance(transaction, dict):
            next_rows.append(transaction)
            continue
        canonical = _canonical_transaction(transaction)
        flag = _modification_of(canonical)
        if _user_set_category(flag):
            next_rows.append(canonical)
            continue
        if _category_from_type_rules(canonical) is not None:
            if canonical.get("hit") not in (None, ""):
                canonical["hit"] = None
                changed = True
            next_rows.append(canonical)
            continue

        existing = parse_hit(canonical.get("hit"))
        if existing is None:
            code, hit = categorize_with_hit(canonical, general, personal_map)
            if canonical.get("category") != code or canonical.get("hit") != hit:
                canonical["category"] = code
                canonical["hit"] = hit
                changed = True
            if flag == MOD_UNCALCULATED:
                canonical["modification"] = MOD_NONE
                changed = True
            next_rows.append(canonical)
            continue

        haystack = _haystack_for_categorization(canonical)
        if not _matches_word(normalized, haystack):
            next_rows.append(canonical)
            continue
        existing_key = _existing_priority_key(canonical, name_by_code)
        if existing_key is not None and existing_key >= new_key:
            next_rows.append(canonical)
            continue
        canonical["category"] = new_code
        canonical["hit"] = new_hit
        if flag == MOD_UNCALCULATED:
            canonical["modification"] = MOD_NONE
        changed = True
        next_rows.append(canonical)

    if not changed:
        return False
    payload["transactions"] = next_rows
    payload = _persist_categorized_store(payload)
    _write_category_totals(payload, general)
    return True


def ircft_remove_term(
    term: str,
    *,
    personal: bool,
    general: dict[str, list[str]],
    personal_map: dict[str, list[str]],
) -> bool:
    """Undo rows whose ``hit`` is this term; full-categorize those rows.

    Unlocked keyword rows with no ``hit`` (legacy JSON) are also fully
    categorized, because the deleted term may have been their winner.
    ``modification`` 1 or 3 keeps ``category`` and only clears a stale hit.
    """
    normalized = _normalize_term(term)
    if not normalized:
        return False
    expected = format_hit(normalized, personal=personal)

    payload = _load_categorized_store()
    transactions = payload.get("transactions")
    if not isinstance(transactions, list):
        return False

    changed = False
    next_rows: list[dict[str, Any]] = []
    for transaction in transactions:
        if not isinstance(transaction, dict):
            next_rows.append(transaction)
            continue
        canonical = _canonical_transaction(transaction)
        flag = _modification_of(canonical)
        parsed = parse_hit(canonical.get("hit"))
        stored = format_hit(parsed[1], personal=parsed[0]) if parsed else None
        type_rule = _category_from_type_rules(canonical) is not None

        if _user_set_category(flag) or type_rule:
            if stored == expected:
                canonical["hit"] = None
                changed = True
            next_rows.append(canonical)
            continue

        if stored != expected and parsed is not None:
            next_rows.append(canonical)
            continue

        code, hit = categorize_with_hit(canonical, general, personal_map)
        if canonical.get("category") != code or canonical.get("hit") != hit:
            canonical["category"] = code
            canonical["hit"] = hit
            changed = True
        if flag == MOD_UNCALCULATED:
            canonical["modification"] = MOD_NONE
            changed = True
        next_rows.append(canonical)

    if not changed:
        return False
    payload["transactions"] = next_rows
    payload = _persist_categorized_store(payload)
    _write_category_totals(payload, general)
    return True


def term_list_diff(before: list[str], after: list[str]) -> tuple[list[str], list[str]]:
    before_set = {_normalize_term(item) for item in before if _normalize_term(item)}
    after_set = {_normalize_term(item) for item in after if _normalize_term(item)}
    removed = [item for item in before_set - after_set]
    added = [item for item in after_set - before_set]
    return added, removed


def apply_ircft_terms(
    *,
    added: list[str],
    removed: list[str],
    personal: bool,
    category_name: str,
) -> None:
    """Run iRCfT for the currently bound person. Terms must already be saved."""
    general = _category_map(_categories_file())
    personal_map = _personal_category_map()
    for term in removed:
        ircft_remove_term(
            term, personal=personal, general=general, personal_map=personal_map
        )
    for term in added:
        ircft_add_term(
            term,
            personal=personal,
            category_name=category_name,
            general=general,
            personal_map=personal_map,
        )


def transactions_for_category(category_name: str) -> list[dict[str, Any]]:
    """Return effective transactions for a category display name (e.g. ``09 Pension``)."""
    from app.category_table_log import log

    code = _category_code(category_name)
    log(
        "filter.start",
        category_name=category_name,
        parsed_code=code,
        store=paths.CATEGORIZED_TRANSACTIONS_PATH,
        store_exists=paths.CATEGORIZED_TRANSACTIONS_PATH.exists(),
    )
    if code is None:
        log("filter.abort", reason="category_name_has_no_numeric_prefix")
        return []

    if _use_sql():
        from app.sql_replica import load_bound_transactions

        rows = load_bound_transactions(category_code=code) or []
        log(
            "filter.done",
            category_name=category_name,
            parsed_code=code,
            raw_transactions=len(rows),
            matched=len(rows),
            source="sql",
        )
        return [_public_transaction(_canonical_transaction(item)) for item in rows if isinstance(item, dict)]

    payload = _load_categorized_store()
    raw_list = payload.get("transactions")
    raw_count = len(raw_list) if isinstance(raw_list, list) else 0

    code_counts: dict[int | str, int] = {}
    transactions: list[dict[str, Any]] = []
    for transaction in raw_list if isinstance(raw_list, list) else []:
        if not isinstance(transaction, dict):
            continue
        effective = _canonical_transaction(transaction)
        effective_code = _as_category_code(effective.get("category"))
        bucket: int | str = effective_code if effective_code is not None else repr(effective.get("category"))
        code_counts[bucket] = code_counts.get(bucket, 0) + 1
        if effective_code == code:
            transactions.append(_public_transaction(effective))

    log(
        "filter.done",
        category_name=category_name,
        parsed_code=code,
        raw_transactions=raw_count,
        modifications=sum(
            1
            for item in (raw_list if isinstance(raw_list, list) else [])
            if isinstance(item, dict) and _modification_of(item) > 0
        ),
        matched=len(transactions),
        code_histogram=dict(sorted(code_counts.items(), key=lambda item: str(item[0]))),
    )
    return transactions


_HIDDEN_TABLE_COLUMNS = frozenset({"id", "currency", "modification", "hit"})
_DESCRIPTION_COLUMN = "description"
_CATEGORY_COLUMN = "category"
_CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£"}


def transaction_display_column_keys(transactions: list[dict[str, Any]]) -> list[str]:
    if not transactions:
        return []
    keys: list[str] = []
    seen: set[str] = set()
    for transaction in transactions:
        for key in transaction:
            if key in _HIDDEN_TABLE_COLUMNS or key in seen:
                continue
            seen.add(key)
            keys.append(key)
    return _category_before_description(keys)


def _category_before_description(keys: list[str]) -> list[str]:
    """Keep ``category`` (C) immediately before ``description``."""
    rest = [key for key in keys if key not in {_CATEGORY_COLUMN, _DESCRIPTION_COLUMN}]
    if _CATEGORY_COLUMN in keys:
        rest.append(_CATEGORY_COLUMN)
    if _DESCRIPTION_COLUMN in keys:
        rest.append(_DESCRIPTION_COLUMN)
    return rest


def _public_transaction(transaction: dict[str, Any]) -> dict[str, Any]:
    return _canonical_transaction(transaction)


def modification_style_ids(payload: dict[str, Any] | None = None) -> tuple[list[str], list[str]]:
    """Return (description_modified_ids, category_modified_ids) from ``modification`` flags."""
    data = payload if payload is not None else _load_categorized_store()
    data = _migrate_categorized_store(
        {
            "transactions": [
                dict(item)
                for item in (data.get("transactions") or [])
                if isinstance(item, dict)
            ],
            "modifications": list(data["modifications"])
            if isinstance(data.get("modifications"), list)
            else [],
        }
    )
    description_ids: list[str] = []
    category_ids: list[str] = []
    for item in data.get("transactions") or []:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        tid = str(item.get("id"))
        flag = _modification_of(item)
        if flag in (MOD_DESCRIPTION, MOD_BOTH):
            description_ids.append(tid)
        if flag in (MOD_CATEGORY, MOD_BOTH):
            category_ids.append(tid)
    return description_ids, category_ids


def format_transaction_amount(transaction: dict[str, Any]) -> str:
    amount = str(transaction.get("amount", "")).strip()
    currency = str(transaction.get("currency", "")).strip().upper()
    symbol = _CURRENCY_SYMBOLS.get(currency, f"{currency} " if currency else "€")
    return f"{symbol}{amount}"


def terms_for_category(category_name: str) -> list[str]:
    """General + personal keyword terms for a category display name."""
    general = _category_map(_categories_file())
    personal = _personal_category_map()
    return [*general.get(category_name, []), *personal.get(category_name, [])]


def category_name_for_column_key(column_key: Any) -> str | None:
    for name in category_names():
        if _category_column_key(name) == column_key:
            return name
    return None


def _normalize_term(term: str) -> str:
    return term.strip().lower()


def _cleaned_terms(terms: list[str]) -> list[str]:
    return [_normalize_term(term) for term in terms if isinstance(term, str) and term.strip()]


def _save_general_category_terms(category_name: str, terms: list[str]) -> None:
    cleaned = _cleaned_terms(terms)
    from app.sql_catalog import save_category_terms

    save_category_terms(category_name, cleaned, person=None)


def _save_personal_category_terms(category_name: str, terms: list[str]) -> None:
    cleaned = _cleaned_terms(terms)
    from app.sql_catalog import save_category_terms

    name = str(paths.BOUND_PERSON or paths.PERSON_NAME or "").strip()
    if not name:
        raise ValueError("personal terms need a bound person")
    save_category_terms(category_name, cleaned, person=name)


def append_category_term(
    category_name: str,
    term: str,
    *,
    group: str,
    person: str,
) -> list[str]:
    """Append one keyword to general (categories.json) or personal (personal_categories.json)."""
    cleaned = _normalize_term(term)
    if not cleaned:
        raise ValueError("term must not be empty")
    if category_name not in category_names():
        raise ValueError(f"Unknown category: {category_name!r}")
    code = _category_code(category_name)
    if code is None or code == DEFAULT_CATEGORY:
        raise ValueError(f"Cannot add terms to category {category_name!r}")

    if group == "general":
        general = _category_map(_categories_file())
        terms = list(general.get(category_name, []))
        if cleaned not in _cleaned_terms(terms):
            terms.append(cleaned)
        _save_general_category_terms(category_name, terms)
    elif group == person:
        personal = _personal_category_map()
        terms = list(personal.get(category_name, []))
        if cleaned not in _cleaned_terms(terms):
            terms.append(cleaned)
        _save_personal_category_terms(category_name, terms)
    else:
        raise ValueError(f"Unknown settings group: {group!r}")
    return terms_for_category(category_name)


def add_category_term(category_name: str, term: str) -> list[str]:
    """Append a term to the personal keyword list for a category."""
    cleaned_term = _normalize_term(term)
    if not cleaned_term:
        return terms_for_category(category_name)
    if cleaned_term in _cleaned_terms(terms_for_category(category_name)):
        return terms_for_category(category_name)

    personal = _personal_category_map()
    personal_terms = list(personal.get(category_name, []))
    personal_terms.append(cleaned_term)
    _save_personal_category_terms(category_name, personal_terms)
    return terms_for_category(category_name)


def remove_category_term(category_name: str, term: str) -> list[str]:
    """Remove a term from personal keywords, otherwise from general keywords."""
    needle = _normalize_term(term)
    personal = _personal_category_map()
    general = _category_map(_categories_file())
    personal_terms = list(personal.get(category_name, []))
    general_terms = list(general.get(category_name, []))

    if any(_normalize_term(existing) == needle for existing in personal_terms):
        _save_personal_category_terms(
            category_name,
            [existing for existing in personal_terms if _normalize_term(existing) != needle],
        )
    elif any(_normalize_term(existing) == needle for existing in general_terms):
        _save_general_category_terms(
            category_name,
            [existing for existing in general_terms if _normalize_term(existing) != needle],
        )
    return terms_for_category(category_name)


def category_terms_table(extra_rows: int = 0) -> tuple[list[tuple[str, str]], list[list[str]]]:
    """Column (name, key) pairs and term rows for the keywords overview table."""
    general = _category_map(_categories_file())
    personal = _personal_category_map()
    category_names = list(general.keys())
    terms_by_category = {
        name: [*general.get(name, []), *personal.get(name, [])] for name in category_names
    }
    max_rows = max((len(terms) for terms in terms_by_category.values()), default=0) + extra_rows
    rows = [
        [
            terms_by_category[name][index] if index < len(terms_by_category[name]) else ""
            for name in category_names
        ]
        for index in range(max_rows)
    ]
    columns = [(name, _category_column_key(name)) for name in category_names]
    return columns, rows


def save_category_terms_column(category_name: str, terms: list[str]) -> list[str]:
    """Persist the merged column term list for a category."""
    cleaned = _cleaned_terms(terms)
    _save_general_category_terms(category_name, cleaned)
    _save_personal_category_terms(category_name, [])
    return terms_for_category(category_name)


def set_category_term_cell(category_name: str, row_index: int, value: str) -> list[str]:
    """Update one CT-table cell and save the column."""
    terms = terms_for_category(category_name)
    cleaned_value = _normalize_term(value) if value.strip() else ""

    if row_index < 0:
        return terms

    if row_index < len(terms):
        if cleaned_value:
            terms[row_index] = cleaned_value
        else:
            terms.pop(row_index)
    elif cleaned_value:
        terms.extend([""] * (row_index - len(terms)))
        terms.append(cleaned_value)

    return save_category_terms_column(category_name, terms)


def _category_column_key(name: str) -> str:
    code = _category_code(name)
    return f"cat_{code}" if code is not None else name.replace(" ", "_")


def category_names() -> list[str]:
    general = _category_map(_categories_file())
    return list(general.keys())


def category_code_set() -> frozenset[int]:
    """Category numbers defined as keys in ``categories.json``."""
    return frozenset(
        code for name in category_names() if (code := _category_code(name)) is not None
    )


def remainder_category_name() -> str:
    """Display name of the default / unmatched category (``DEFAULT_CATEGORY``)."""
    for name in category_names():
        if _category_code(name) == DEFAULT_CATEGORY:
            return name
    return f"{DEFAULT_CATEGORY:04d} Unclassified expenses"


def _validate_category_code(code: Any) -> int:
    try:
        numeric = int(code)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid category code: {code!r}") from exc
    if numeric not in category_code_set():
        known = ", ".join(str(c) for c in sorted(category_code_set()))
        raise ValueError(f"Unknown category code {numeric}; known codes: {known}")
    return numeric


def _source_transaction_by_id(
    transaction_id: str, payload: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Return the stored transaction for ``id`` (values already effective)."""
    data = payload if payload is not None else _load_categorized_store()
    data = _migrate_categorized_store(data)
    for transaction in data.get("transactions", []):
        if isinstance(transaction, dict) and str(transaction.get("id", "")) == transaction_id:
            return _canonical_transaction(transaction)
    return None


def record_modification(transaction: dict[str, Any]) -> dict[str, Any]:
    """Overwrite category and/or description on the row; update ``modification``.

    ``transaction`` is the edited row from the UI.  M bits: 1 = category, 2 =
    description, 3 = both. Recalc will not replace a user-set category.
    """
    data = _load_categorized_store()
    if not data:
        data = {"transactions": []}

    submitted = _canonical_transaction(transaction)
    transaction_id = str(submitted.get("id", ""))
    if not transaction_id:
        raise ValueError("Transaction id is required for a modification")

    if "category" in submitted and submitted.get("category") is not None:
        submitted["category"] = _validate_category_code(submitted.get("category"))

    stored: dict[str, Any] | None = None
    for item in data.get("transactions", []):
        if isinstance(item, dict) and str(item.get("id", "")) == transaction_id:
            stored = item
            break
    if stored is None:
        raise ValueError(f"Transaction not found: {transaction_id}")

    base = _canonical_transaction(stored)
    cat_changed = "category" in submitted and not _values_equal(
        "category", submitted.get("category"), base.get("category")
    )
    desc_changed = "description" in submitted and not _values_equal(
        "description", submitted.get("description"), base.get("description")
    )
    if cat_changed:
        stored["category"] = submitted["category"]
    if desc_changed:
        stored["description"] = submitted["description"]
    if cat_changed or desc_changed:
        stored["modification"] = _with_mod_bits(
            _modification_of(base),
            category=cat_changed,
            description=desc_changed,
        )
    else:
        stored["modification"] = _modification_of(base)

    if _use_sql():
        from app.sql_replica import sync_bound_transactions

        sync_bound_transactions([stored])
    else:
        data = _persist_categorized_store(data)
    general = _category_map(_categories_file())
    _write_category_totals(data, general)
    return _public_transaction(_canonical_transaction(stored))


def record_category_change(transaction: dict[str, Any], category_name: str) -> dict[str, Any]:
    """Record a category overwrite for this transaction id."""
    code = _category_code(category_name)
    if code is None:
        raise ValueError(f"Unknown category: {category_name!r}")

    transaction_id = str(transaction.get("id", ""))
    effective = _source_transaction_by_id(transaction_id) or dict(transaction)
    modified = dict(effective)
    modified["category"] = code
    return record_modification(modified)


def process_transactions(raw_transactions: list[dict[str, Any]], new_year: bool) -> dict[str, str]:
    """Persist new bank rows uncategorized, then categorize automatically.

    New rows are written with ``modification`` -1 and ``hit`` NULL, then
    ``recategorize_transactions`` fills category/hit. Existing rows keep
    their stored category and modification.
    """
    new_records = _simplify_uncategorized(raw_transactions)
    from app.sql_replica import ingest_bound_transactions

    ingest_bound_transactions(new_records)
    return recategorize_transactions()


def load_transaction_split(source_id: str) -> dict[str, Any]:
    """Load the original booking and its split lines for the bound person."""
    from app.sql_replica import (
        _root_source_id,
        _split_payload,
        load_bound_split,
    )

    if _use_sql():
        return load_bound_split(source_id)
    needle = str(source_id or "").strip()
    if not needle:
        raise ValueError("Transaction id is required")
    data = _load_categorized_store()
    rows = [item for item in (data.get("transactions") or []) if isinstance(item, dict)]
    parent_id = _root_source_id(needle)
    by_id = {str(item.get("id") or ""): item for item in rows}
    parent = by_id.get(parent_id)
    if parent is None:
        raise ValueError(f"Transaction not found: {parent_id}")
    prefix = f"{parent_id}~s"
    children = [
        item
        for item in rows
        if str(item.get("id") or "").startswith(prefix)
        and _root_source_id(str(item.get("id") or "")) == parent_id
    ]
    children.sort(key=lambda item: str(item.get("id") or ""))
    payload = _split_payload(parent_id=parent_id, parent=parent, children=children)
    return payload


def save_transaction_split(
    source_id: str,
    *,
    description: str,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist split lines. Parent amount is computed so the group total is unchanged."""
    from app.sql_replica import save_bound_split

    return save_bound_split(source_id, description=description, lines=lines)

