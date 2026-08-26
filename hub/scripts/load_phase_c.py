"""Load workspaces JSON into SQL Server (Phase C replica). Hub writes stay on JSON."""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

HUB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB_ROOT))
sys.path.insert(0, str(HUB_ROOT.parent / "shared"))

from app.core.categorize import DEFAULT_CATEGORY  # noqa: E402
from app.runtime import data_root  # noqa: E402
from app.yearpath import is_year_name  # noqa: E402

SCHEMA_PATH = HUB_ROOT / "sql" / "phase_c.sql"

COUNTRIES: list[tuple[int, str, str]] = [
    (1, "nederland", "EUR"),
    (2, "uk", "GBP"),
    (3, "stichtingen", "EUR"),
]
COUNTRY_FOLDERS = {folder: country_id for country_id, folder, _ in COUNTRIES}


def transaction_table(folder: str) -> str:
    if folder not in COUNTRY_FOLDERS:
        raise LoadError(f"No transaction table for country folder {folder!r}")
    return f"dbo.transaction_{folder}"

BANKS: list[tuple[int, str, str, str]] = [
    (1, "NatWest", "Natwest", "csv"),
    (2, "Royal Bank of Scotland", "RBS", "csv"),
    (3, "Lloyds Bank", "LLOYDS", "csv"),
    (5, "Bank of Scotland", "BoS", "csv"),
]

IGNORE_DIRS = frozenset(
    {
        "secret",
        "app",
        "frontend",
        "dist",
        "build",
        ".venv",
        "venv",
        "scripts",
        "node_modules",
        "__pycache__",
        ".git",
    }
)

_ENABLE_BANKING_ID = re.compile(r"^(\d+)_(\d+)$")
_LOCAL_CODE = re.compile(r"^(\d{2})\b")
_DATE_DMY = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")


class LoadError(RuntimeError):
    pass


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = _read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise LoadError(f"Invalid JSON: {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _category_map(data: dict[str, Any]) -> dict[str, list[str]]:
    nested = data.get("categories")
    raw = nested if isinstance(nested, dict) else data
    out: dict[str, list[str]] = {}
    for label, terms in raw.items():
        if label in ("table_header_terms", "abbreviations"):
            continue
        if isinstance(terms, list):
            out[str(label)] = [str(term) for term in terms]
    return out


def local_code_from_label(label: str) -> int | None:
    match = _LOCAL_CODE.match(str(label).strip())
    if match:
        return int(match.group(1))
    try:
        return int(str(label)[:2])
    except ValueError:
        return None


def parse_amount(raw: Any, *, path: Path) -> Decimal:
    text = str(raw or "").strip().replace(",", ".")
    if not text:
        raise LoadError(f"{path}: empty amount")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise LoadError(f"{path}: bad amount {raw!r}") from exc


def parse_booked_on(raw: Any, *, path: Path) -> date:
    text = str(raw or "").strip()
    match = _DATE_DMY.fullmatch(text)
    if match:
        day, month, year = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return date(year, month, day)
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            pass
    raise LoadError(f"{path}: bad date {raw!r}")


def parse_uuid(raw: Any) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return str(UUID(text))
    except ValueError as exc:
        raise LoadError(f"Invalid uid {raw!r}") from exc


def _dirs(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    return sorted(
        (
            child
            for child in path.iterdir()
            if child.is_dir() and not child.name.startswith(".") and child.name not in IGNORE_DIRS
        ),
        key=lambda item: item.name.lower(),
    )


def _has_person_layout(folder: Path) -> bool:
    if (folder / "secret").is_dir():
        return True
    return any(child.is_dir() and is_year_name(child.name) for child in folder.iterdir())


def _year_dirs(person_folder: Path) -> list[Path]:
    return sorted(
        (child for child in person_folder.iterdir() if child.is_dir() and is_year_name(child.name)),
        key=lambda item: item.name,
    )


def resolve_bank_folder(name: str, banks_by_folder: dict[str, int]) -> int:
    if name in banks_by_folder:
        return banks_by_folder[name]
    best = ""
    best_id = 0
    for folder, bank_id in banks_by_folder.items():
        if name.startswith(f"{folder}_") and len(folder) > len(best):
            best = folder
            best_id = bank_id
    if best_id:
        return best_id
    known = ", ".join(sorted(banks_by_folder))
    raise LoadError(f"Unknown bank folder {name!r} (known: {known})")


def processor_for_bank(folder: str, file_format: str) -> str:
    return f"{folder}-{file_format}"


def _connect():
    from app import user_store

    if not user_store.database_url():
        raise SystemExit("Set HUB_DATABASE_URL (see hub/.env.example)")
    return user_store._sql_connect()


def _exec_script(cursor, sql: str) -> None:
    for raw_batch in sql.split(";"):
        batch = raw_batch.strip()
        if batch:
            cursor.execute(batch)


def _profile_accounts(person_folder: Path) -> list[dict[str, Any]]:
    profile = _read_json_object(person_folder / "secret" / "profile.json")
    accounts: list[dict[str, Any]] = []
    for conn in profile.get("connections") or []:
        if not isinstance(conn, dict):
            continue
        for acc in conn.get("accounts") or []:
            if isinstance(acc, dict) and str(acc.get("iban") or "").strip():
                accounts.append(acc)
    return accounts


def _collect_account_snapshots(person_folder: Path) -> list[tuple[int, dict[str, Any]]]:
    """(year, account_balances row) from every year-level totals file, latest year last."""
    rows: list[tuple[int, dict[str, Any]]] = []
    for year_dir in _year_dirs(person_folder):
        totals = _read_json_object(year_dir / "category_totals.json")
        balances = totals.get("account_balances") or []
        if not isinstance(balances, list):
            continue
        year = int(year_dir.name)
        for item in balances:
            if isinstance(item, dict):
                rows.append((year, item))
    return rows


def _seed_accounts_from_disk(person_folder: Path) -> list[dict[str, Any]]:
    by_iban: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for _year, item in _collect_account_snapshots(person_folder):
        iban = str(item.get("iban") or "").strip()
        if not iban:
            continue
        if iban not in by_iban:
            order.append(iban)
        by_iban[iban] = {
            "iban": iban,
            "account_name": str(item.get("name") or iban)[:64],
            "balance": parse_amount(item.get("balance") or "0", path=person_folder),
            "files": [str(name) for name in (item.get("files") or []) if str(name).strip()],
        }
    for acc in _profile_accounts(person_folder):
        iban = str(acc.get("iban") or "").strip()
        if not iban:
            continue
        if iban not in by_iban:
            order.append(iban)
            by_iban[iban] = {
                "iban": iban,
                "account_name": str(acc.get("name") or iban)[:64],
                "balance": parse_amount(acc.get("balance") or "0", path=person_folder),
                "files": [],
            }
    if not order:
        placeholder = f"UNKNOWN:{person_folder.parent.parent.name}/{person_folder.parent.name}/{person_folder.name}"
        return [
            {
                "iban": placeholder[:64],
                "account_name": person_folder.name[:64],
                "balance": Decimal("0"),
                "files": [],
            }
        ]
    return [by_iban[iban] for iban in order]


def _category_id_for_label(
    *,
    country_id: int,
    label: str,
    by_label: dict[tuple[int, str], int],
    by_code: dict[tuple[int, int], int],
    allow_footer_skip: bool = False,
) -> int | None:
    key = (country_id, label)
    if key in by_label:
        return by_label[key]
    code = local_code_from_label(label)
    if code is not None:
        found = by_code.get((country_id, code))
        if found is not None:
            return found
        raise LoadError(f"No dim_category for country_id={country_id} local_code={code} label={label!r}")
    if allow_footer_skip:
        return None
    raise LoadError(f"No dim_category for country_id={country_id} label={label!r}")


def _category_id_for_local_code(
    country_id: int,
    local_code: int,
    by_code: dict[tuple[int, int], int],
    *,
    path: Path,
) -> int:
    found = by_code.get((country_id, local_code))
    if found is None:
        raise LoadError(f"{path}: no dim_category for country_id={country_id} local_code={local_code}")
    return found


def _own_iban_set(accounts: list[dict[str, Any]]) -> set[str]:
    return {str(acc["iban"]).strip() for acc in accounts}


def resolve_account(
    *,
    accounts: list[dict[str, Any]],
    tx: dict[str, Any],
    bank_folder: str | None,
    banks: list[tuple[int, str, str, str]],
    path: Path,
) -> dict[str, Any]:
    if len(accounts) == 1:
        return accounts[0]

    if bank_folder:
        matched = [
            acc
            for acc in accounts
            if any(bank_folder.lower() in str(name).lower() for name in acc.get("files") or [])
        ]
        if len(matched) == 1:
            return matched[0]
        if len(matched) > 1:
            raise LoadError(f"{path}: several accounts match bank folder {bank_folder!r}")

    bank_type = str(tx.get("type") or "").strip()
    for _bank_id, _official, folder, file_format in banks:
        processor = processor_for_bank(folder, file_format)
        if bank_type.lower() != processor.lower():
            continue
        matched = [
            acc
            for acc in accounts
            if any(folder.lower() in str(name).lower() for name in acc.get("files") or [])
        ]
        if len(matched) == 1:
            return matched[0]
        if len(matched) == 0 and bank_folder:
            break

    iban = str(tx.get("iban") or "").strip()
    if iban:
        matched = [acc for acc in accounts if acc["iban"] == iban]
        if len(matched) == 1:
            return matched[0]

    source_id = str(tx.get("id") or "").strip()
    eb = _ENABLE_BANKING_ID.fullmatch(source_id)
    if eb:
        index = int(eb.group(2))
        if 0 <= index < len(accounts):
            return accounts[index]
        raise LoadError(f"{path}: account index {index} out of range for {source_id}")

    raise LoadError(
        f"{path}: cannot resolve account for id={source_id!r} type={bank_type!r} iban={iban!r}"
    )


def _modifications_by_id(payload: dict[str, Any], *, path: Path) -> dict[str, dict[str, Any]]:
    raw = payload.get("modifications") or []
    if not isinstance(raw, list):
        raise LoadError(f"{path}: modifications must be a list")
    out: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("id") or "").strip()
        if not source_id:
            raise LoadError(f"{path}: modification missing id")
        out[source_id] = item
    return out


def _sql_hit(raw: dict[str, Any], *, path: Path, source_id: str) -> str | None:
    value = raw.get("hit")
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not (text.startswith("P:") or text.startswith("G:")):
        return None
    if len(text) > 64:
        raise LoadError(f"{path}: hit exceeds 64 characters on {source_id}")
    return text


def apply_schema(cursor) -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    _exec_script(cursor, sql)


def seed_countries(cursor) -> None:
    cursor.executemany(
        "INSERT INTO dbo.country (country_id, folder, currency_default) VALUES (?, ?, ?)",
        COUNTRIES,
    )


def seed_banks(cursor) -> None:
    cursor.executemany(
        """
        INSERT INTO dbo.bank (bank_id, bank_name_official, bank_name_folder, file_format)
        VALUES (?, ?, ?, ?)
        """,
        BANKS,
    )


def seed_categories(cursor, root: Path) -> tuple[dict[tuple[int, int], int], dict[tuple[int, str], int]]:
    by_code: dict[tuple[int, int], int] = {}
    by_label: dict[tuple[int, str], int] = {}
    term_rows: list[tuple[int, str, int]] = []
    abbr_rows: list[tuple[int, str, str]] = []
    for country_id, folder, _currency in COUNTRIES:
        path = root / folder / "categories.json"
        payload = _read_json_object(path)
        categories = payload.get("categories")
        if not isinstance(categories, dict) or not categories:
            raise LoadError(f"Missing categories in {path}")
        footers = 0
        for index, (label, terms) in enumerate(categories.items()):
            category_id = country_id * 100 + index
            code = local_code_from_label(label)
            matrix_role = None
            if code is None:
                if footers == 0:
                    code = 22
                    matrix_role = "balance"
                elif footers == 1:
                    code = 23
                    matrix_role = "last_booked"
                else:
                    raise LoadError(f"{path}: extra footer label {label!r}")
                footers += 1
            is_remainder = 1 if code == DEFAULT_CATEGORY else 0
            cursor.execute(
                """
                INSERT INTO dbo.dim_category
                    (category_id, country_id, local_code, label, is_remainder, matrix_role)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                category_id,
                country_id,
                code,
                str(label),
                is_remainder,
                matrix_role,
            )
            by_code[(country_id, code)] = category_id
            by_label[(country_id, str(label))] = category_id
            if isinstance(terms, list) and matrix_role is None:
                for sort_order, term in enumerate(terms):
                    text = str(term)
                    if text:
                        term_rows.append((category_id, text, sort_order))
        abbreviations = payload.get("abbreviations") or {}
        if isinstance(abbreviations, dict):
            for bank_type, abbreviation in abbreviations.items():
                abbr_rows.append((country_id, str(bank_type), str(abbreviation)[:16]))
    if term_rows:
        cursor.executemany(
            """
            INSERT INTO dbo.category_term (category_id, person_id, term, sort_order)
            VALUES (?, NULL, ?, ?)
            """,
            term_rows,
        )
    if abbr_rows:
        cursor.executemany(
            """
            INSERT INTO dbo.type_abbreviation (country_id, bank_type, abbreviation)
            VALUES (?, ?, ?)
            """,
            abbr_rows,
        )
    return by_code, by_label


def _insert_center(cursor, country_id: int, folder: str) -> int:
    cursor.execute(
        "INSERT INTO dbo.center (country_id, folder) OUTPUT INSERTED.center_id VALUES (?, ?)",
        country_id,
        folder,
    )
    return int(cursor.fetchone()[0])


def _insert_person(cursor, center_id: int, folder: str, number_accounts: int) -> int:
    cursor.execute(
        """
        INSERT INTO dbo.person (center_id, folder, number_accounts)
        OUTPUT INSERTED.person_id
        VALUES (?, ?, ?)
        """,
        center_id,
        folder,
        number_accounts,
    )
    return int(cursor.fetchone()[0])


def _insert_account(cursor, person_id: int, acc: dict[str, Any]) -> int:
    cursor.execute(
        """
        INSERT INTO dbo.account (person_id, iban, account_name, balance)
        OUTPUT INSERTED.account_id
        VALUES (?, ?, ?, ?)
        """,
        person_id,
        acc["iban"],
        acc["account_name"],
        acc["balance"],
    )
    return int(cursor.fetchone()[0])


def load_tree(
    cursor,
    root: Path,
    *,
    by_code: dict[tuple[int, int], int],
    by_label: dict[tuple[int, str], int],
) -> None:
    banks_by_folder = {folder: bank_id for bank_id, _official, folder, _fmt in BANKS}
    unexpected = [
        child.name
        for child in root.iterdir()
        if child.is_dir()
        and not child.name.startswith(".")
        and child.name not in IGNORE_DIRS
        and child.name not in COUNTRY_FOLDERS
    ]
    if unexpected:
        raise LoadError(f"Unexpected country folder(s) under {root}: {unexpected}")

    tx_rows: dict[str, list[tuple[Any, ...]]] = {folder: [] for _id, folder, _cur in COUNTRIES}
    personal_terms: list[tuple[int, int, str, int]] = []
    total_rows: list[tuple[Any, ...]] = []
    balance_specs: list[tuple[int, int, int | None, int, str, Decimal, str | None, list[str]]] = []

    for country_id, country_folder, _currency in COUNTRIES:
        country_dir = root / country_folder
        if not country_dir.is_dir():
            raise LoadError(f"Missing country folder {country_dir}")
        for center_dir in _dirs(country_dir):
            people_dirs = [child for child in _dirs(center_dir) if _has_person_layout(child)]
            if not people_dirs:
                continue
            center_id = _insert_center(cursor, country_id, center_dir.name)
            for person_dir in people_dirs:
                accounts = _seed_accounts_from_disk(person_dir)
                person_id = _insert_person(cursor, center_id, person_dir.name, len(accounts))
                for acc in accounts:
                    acc["account_id"] = _insert_account(cursor, person_id, acc)
                accounts_by_iban = {acc["iban"]: acc for acc in accounts}

                personal_path = person_dir / "secret" / "personal_categories.json"
                for label, terms in _category_map(_read_json_object(personal_path)).items():
                    category_id = _category_id_for_label(
                        country_id=country_id,
                        label=label,
                        by_label=by_label,
                        by_code=by_code,
                    )
                    if category_id is None:
                        continue
                    for sort_order, term in enumerate(terms):
                        text = str(term)
                        if text:
                            personal_terms.append((category_id, person_id, text, sort_order))

                for year_dir in _year_dirs(person_dir):
                    year = int(year_dir.name)
                    bank_dirs = [
                        child
                        for child in year_dir.iterdir()
                        if child.is_dir() and not child.name.startswith(".")
                    ]
                    sources: list[tuple[Path, int | None, str | None]] = [
                        (year_dir / "categorized_transactions.json", None, None)
                    ]
                    totals_sources: list[tuple[Path, int | None]] = [
                        (year_dir / "category_totals.json", None)
                    ]
                    for bank_dir in bank_dirs:
                        bank_id = resolve_bank_folder(bank_dir.name, banks_by_folder)
                        sources.append(
                            (bank_dir / "categorized_transactions.json", bank_id, bank_dir.name)
                        )
                        totals_sources.append((bank_dir / "category_totals.json", bank_id))

                    for tx_path, bank_id, bank_folder in sources:
                        if not tx_path.is_file():
                            continue
                        payload = _read_json_object(tx_path)
                        mods = _modifications_by_id(payload, path=tx_path)
                        records = payload.get("transactions") or []
                        if not isinstance(records, list):
                            raise LoadError(f"{tx_path}: transactions must be a list")
                        for raw in records:
                            if not isinstance(raw, dict):
                                continue
                            source_id = str(raw.get("id") or "").strip()
                            if not source_id:
                                raise LoadError(f"{tx_path}: transaction missing id")
                            local_code = raw.get("category")
                            try:
                                local_int = int(local_code)
                            except (TypeError, ValueError) as exc:
                                raise LoadError(f"{tx_path}: bad category on {source_id}") from exc
                            description = str(raw.get("description") or "")
                            cat_bit = False
                            desc_bit = False
                            mod = mods.get(source_id)
                            if mod:
                                if "description" in mod and mod.get("description") is not None:
                                    description = str(mod.get("description") or "")
                                    desc_bit = True
                                if "category" in mod and mod.get("category") is not None:
                                    try:
                                        local_int = int(mod["category"])
                                    except (TypeError, ValueError) as exc:
                                        raise LoadError(
                                            f"{tx_path}: bad modification category for {source_id}"
                                        ) from exc
                                    cat_bit = True
                            if raw.get("modification") is not None:
                                try:
                                    modification = int(raw.get("modification"))
                                except (TypeError, ValueError) as exc:
                                    raise LoadError(f"{tx_path}: bad modification on {source_id}") from exc
                            else:
                                modification = 0
                                if cat_bit:
                                    modification |= 1
                                if desc_bit:
                                    modification |= 2
                            if modification == -1:
                                category_id = None
                            else:
                                category_id = _category_id_for_local_code(
                                    country_id, local_int, by_code, path=tx_path
                                )
                            account = resolve_account(
                                accounts=accounts,
                                tx=raw,
                                bank_folder=bank_folder,
                                banks=BANKS,
                                path=tx_path,
                            )
                            iban = str(raw.get("iban") or "").strip()
                            tx_rows[country_folder].append(
                                (
                                    person_id,
                                    account["account_id"],
                                    year,
                                    bank_id,
                                    source_id,
                                    parse_amount(raw.get("amount"), path=tx_path),
                                    str(raw.get("currency") or "EUR")[:3],
                                    str(raw.get("type") or "")[:64] or None,
                                    str(raw.get("name") or "")[:512] or None,
                                    iban[:64] or None,
                                    description or None,
                                    parse_booked_on(raw.get("date"), path=tx_path),
                                    category_id,
                                    modification,
                                    _sql_hit(raw, path=tx_path, source_id=source_id),
                                )
                            )

                    for totals_path, bank_id in totals_sources:
                        if not totals_path.is_file():
                            continue
                        totals = _read_json_object(totals_path)
                        categories = totals.get("categories") or {}
                        if isinstance(categories, dict):
                            for label, amount in categories.items():
                                category_id = _category_id_for_label(
                                    country_id=country_id,
                                    label=str(label),
                                    by_label=by_label,
                                    by_code=by_code,
                                    allow_footer_skip=True,
                                )
                                if category_id is None:
                                    continue
                                total_rows.append(
                                    (
                                        person_id,
                                        year,
                                        bank_id,
                                        category_id,
                                        parse_amount(amount, path=totals_path),
                                    )
                                )
                        for item in totals.get("account_balances") or []:
                            if not isinstance(item, dict):
                                continue
                            iban = str(item.get("iban") or "").strip()
                            acc = accounts_by_iban.get(iban)
                            if acc is None:
                                raise LoadError(f"{totals_path}: unknown IBAN {iban!r}")
                            files = [str(name) for name in (item.get("files") or []) if str(name).strip()]
                            balance_specs.append(
                                (
                                    person_id,
                                    year,
                                    bank_id,
                                    int(acc["account_id"]),
                                    str(item.get("currency") or "EUR")[:3],
                                    parse_amount(item.get("balance") or "0", path=totals_path),
                                    parse_uuid(item.get("uid")),
                                    files,
                                )
                            )

                cursor.execute(
                    """
                    UPDATE dbo.person
                    SET number_accounts = (SELECT COUNT(*) FROM dbo.account WHERE person_id = ?)
                    WHERE person_id = ?
                    """,
                    person_id,
                    person_id,
                )

    if personal_terms:
        cursor.executemany(
            """
            INSERT INTO dbo.category_term (category_id, person_id, term, sort_order)
            VALUES (?, ?, ?, ?)
            """,
            personal_terms,
        )
    tx_insert = """
            INSERT INTO {table} (
                person_id, account_id, year, bank_id, source_id, amount, currency,
                bank_type, counterparty_name, counterparty_iban, description,
                booked_on, category_id, modification, hit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
    for folder, rows in tx_rows.items():
        if not rows:
            continue
        cursor.fast_executemany = True
        cursor.executemany(tx_insert.format(table=transaction_table(folder)), rows)
        cursor.fast_executemany = False
    if total_rows:
        cursor.executemany(
            """
            INSERT INTO dbo.category_total (person_id, year, bank_id, category_id, amount)
            VALUES (?, ?, ?, ?, ?)
            """,
            total_rows,
        )
    for spec in balance_specs:
        person_id, year, bank_id, account_id, currency, balance, uid, files = spec
        cursor.execute(
            """
            INSERT INTO dbo.account_balance
                (person_id, year, bank_id, account_id, currency, balance, uid)
            OUTPUT INSERTED.account_balance_id
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            person_id,
            year,
            bank_id,
            account_id,
            currency,
            balance,
            uid,
        )
        balance_id = int(cursor.fetchone()[0])
        if files:
            cursor.executemany(
                """
                INSERT INTO dbo.account_balance_file (account_balance_id, file_name, sort_order)
                VALUES (?, ?, ?)
                """,
                [(balance_id, name, index) for index, name in enumerate(files)],
            )

    booked_union = " UNION ALL ".join(
        f"SELECT account_id, booked_on FROM {transaction_table(folder)}"
        for _id, folder, _cur in COUNTRIES
    )
    cursor.execute(
        f"""
        UPDATE a
        SET last_booked = x.mx
        FROM dbo.account a
        INNER JOIN (
            SELECT account_id, MAX(booked_on) AS mx
            FROM ({booked_union}) booked
            GROUP BY account_id
        ) x ON x.account_id = a.account_id
        """
    )
    cursor.execute(
        """
        UPDATE a
        SET balance = x.balance
        FROM dbo.account a
        INNER JOIN (
            SELECT ab.account_id, ab.balance,
                   ROW_NUMBER() OVER (PARTITION BY ab.account_id ORDER BY ab.year DESC) AS rn
            FROM dbo.account_balance ab
        ) x ON x.account_id = a.account_id AND x.rn = 1
        """
    )


def verify(cursor) -> None:
    def one(sql: str, *params: Any) -> Any:
        cursor.execute(sql, *params)
        row = cursor.fetchone()
        if row is None:
            raise LoadError(f"Check failed (no row): {sql}")
        return row

    cursor.execute("SELECT COUNT(*) FROM dbo.country")
    print(f"countries: {cursor.fetchone()[0]}")
    cursor.execute("SELECT COUNT(*) FROM dbo.bank")
    print(f"banks: {cursor.fetchone()[0]}")
    cursor.execute("SELECT COUNT(*) FROM dbo.dim_category")
    print(f"categories: {cursor.fetchone()[0]}")
    cursor.execute("SELECT COUNT(*) FROM dbo.center")
    print(f"centers: {cursor.fetchone()[0]}")
    cursor.execute("SELECT COUNT(*) FROM dbo.person")
    print(f"people: {cursor.fetchone()[0]}")
    cursor.execute("SELECT COUNT(*) FROM dbo.account")
    print(f"accounts: {cursor.fetchone()[0]}")
    total_tx = 0
    for _id, folder, _cur in COUNTRIES:
        cursor.execute(f"SELECT COUNT(*) FROM {transaction_table(folder)}")
        count = int(cursor.fetchone()[0])
        total_tx += count
        print(f"transactions_{folder}: {count}")
    print(f"transactions: {total_tx}")

    cursor.execute(
        """
        SELECT c.folder, d.category_id, d.local_code, d.label
        FROM dbo.dim_category d
        JOIN dbo.country c ON c.country_id = d.country_id
        WHERE d.local_code = 12
        ORDER BY d.category_id
        """
    )
    print("local_code 12:")
    for row in cursor.fetchall():
        print(f"  {row[0]} {row[1]} {row[2]} {row[3]}")

    calc, modification, label = one(
        """
        SELECT t.category_id, t.modification, d.label
        FROM dbo.transaction_nederland t
        JOIN dbo.person p ON p.person_id = t.person_id
        JOIN dbo.dim_category d ON d.category_id = t.category_id
        WHERE p.folder = N'anton_schins'
          AND t.source_id = N'010305258369428750000000_0'
          AND t.bank_id IS NULL
        """
    )
    if int(calc) != 104 or int(modification) != 0 or str(label) != "12 Vervoer":
        raise LoadError(
            f"anton check failed: category_id={calc} modification={modification} label={label!r} "
            "(expected 104, 0, '12 Vervoer')"
        )
    print("check anton 010305258369428750000000_0: 104 / modification 0 / 12 Vervoer")

    set_id, set_mod, set_label = one(
        """
        SELECT t.category_id, t.modification, d.label
        FROM dbo.transaction_nederland t
        JOIN dbo.dim_category d ON d.category_id = t.category_id
        WHERE t.source_id = N'010305251322603690000000_0'
          AND t.bank_id IS NULL
        """
    )
    if int(set_id) != 110 or int(set_mod) != 1 or str(set_label) != "19 Giften":
        raise LoadError(
            f"anton override failed: category_id={set_id} modification={set_mod} label={set_label!r}"
        )
    print("check anton modification: category_id 110 / modification 1 / 19 Giften")

    for folder, table in (("uk", "dbo.transaction_uk"), ("stichtingen", "dbo.transaction_stichtingen")):
        cursor.execute(
            f"""
            SELECT TOP 1 t.category_id
            FROM {table} t
            JOIN dbo.dim_category d ON d.category_id = t.category_id
            WHERE d.local_code = 12
            """
        )
        other = cursor.fetchone()
        if other is not None:
            other_id = int(other[0])
            if other_id == 104:
                raise LoadError(f"{folder} JSON 12 joined to 104")
            print(f"check {table} local 12 -> {other_id} (not 104)")
        else:
            cursor.execute(
                """
                SELECT d.category_id
                FROM dbo.dim_category d
                JOIN dbo.country c ON c.country_id = d.country_id
                WHERE d.local_code = 12 AND c.folder = ?
                """,
                folder,
            )
            category_id = int(cursor.fetchone()[0])
            if category_id == 104:
                raise LoadError(f"{folder} local 12 is 104")
            print(f"check {folder} dim local 12 -> {category_id} (not 104)")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM dbo.transaction_uk t
        JOIN dbo.person p ON p.person_id = t.person_id
        JOIN dbo.center n ON n.center_id = p.center_id
        JOIN dbo.country c ON c.country_id = n.country_id
        WHERE c.folder <> N'uk'
        """
    )
    if int(cursor.fetchone()[0]):
        raise LoadError("transaction_uk contains a row whose person is not uk")
    print("check each booking table is country-scoped")

    cursor.execute(
        """
        SELECT p.folder, p.number_accounts, COUNT(a.account_id)
        FROM dbo.person p
        JOIN dbo.account a ON a.person_id = p.person_id
        GROUP BY p.person_id, p.folder, p.number_accounts
        HAVING p.number_accounts <> COUNT(a.account_id)
        """
    )
    mismatches = cursor.fetchall()
    if mismatches:
        raise LoadError(f"number_accounts mismatch: {mismatches}")
    print("check number_accounts = COUNT(account)")

    for folder, expected in (("xavier_bosch", 4), ("SDOG", 5), ("anton_schins", 1)):
        count, distinct_people = one(
            """
            SELECT COUNT(*), COUNT(DISTINCT a.person_id)
            FROM dbo.account a
            JOIN dbo.person p ON p.person_id = a.person_id
            WHERE p.folder = ?
            """,
            folder,
        )
        if int(count) != expected or int(distinct_people) != 1:
            raise LoadError(
                f"{folder}: expected {expected} accounts on one person_id, got {count}/{distinct_people}"
            )
        print(f"check {folder}: {count} accounts, one person_id")


def main() -> None:
    root = data_root()
    started = datetime.now()
    conn = _connect()
    cursor = conn.cursor()
    try:
        apply_schema(cursor)
        seed_countries(cursor)
        seed_banks(cursor)
        by_code, by_label = seed_categories(cursor, root)
        load_tree(cursor, root, by_code=by_code, by_label=by_label)
        verify(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    elapsed = (datetime.now() - started).total_seconds()
    print(f"phase C load complete in {elapsed:.1f}s (SQL replica; hub writes still JSON)")


if __name__ == "__main__":
    main()
