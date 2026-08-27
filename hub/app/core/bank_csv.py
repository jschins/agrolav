"""Bank CSV upload layout: modalities, subfolders, year consolidation."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.core.excel_import import build_category_totals, category_name_map
from app.paths import PersonPack
from app.runtime import data_root

CONSOLIDATED_VIEW = "consolidated"

CSV_FORMATS = frozenset({"bos-csv", "lloyds-csv", "rbs-csv", "natwest-csv"})
DEBIT_CREDIT_FORMATS = frozenset({"bos-csv", "lloyds-csv"})
VALUE_BALANCE_FORMATS = frozenset({"rbs-csv", "natwest-csv"})


def normalize_upload_format(fmt: str | None) -> str:
    """``excel`` | ``test`` | ``bos-csv`` | ``lloyds-csv`` | ``rbs-csv`` | ``natwest-csv``."""
    value = str(fmt or "Excel").strip().lower().replace("_", "-")
    if value == "test":
        return "test"
    aliases = {
        "bos-csv": "bos-csv",
        "bos csv": "bos-csv",
        "bos": "bos-csv",
        "lloyds-csv": "lloyds-csv",
        "lloyds csv": "lloyds-csv",
        "lloyds": "lloyds-csv",
        "rbs-csv": "rbs-csv",
        "rbs csv": "rbs-csv",
        "rbs": "rbs-csv",
        "natwest-csv": "natwest-csv",
        "natwest csv": "natwest-csv",
        "natwest": "natwest-csv",
        # legacy
        "bos-lloyds-csv": "lloyds-csv",
        "bos-lloyds csv": "lloyds-csv",
    }
    if value in aliases:
        return aliases[value]
    return "excel"


def is_csv_bank_format(fmt: str) -> bool:
    return normalize_upload_format(fmt) in CSV_FORMATS


def csv_layout(fmt: str) -> str:
    normalized = normalize_upload_format(fmt)
    if normalized in DEBIT_CREDIT_FORMATS:
        return "debit_credit"
    if normalized in VALUE_BALANCE_FORMATS:
        return "value_balance"
    raise ValueError(f"Not a bank CSV format: {fmt!r}")


_DEFAULT_BANK_MODALITIES = {
    "BoS": "bos-csv",
    "LLOYDS": "lloyds-csv",
    "RBS": "rbs-csv",
    "Natwest": "natwest-csv",
}


def _acl_document() -> dict[str, Any]:
    from app import user_store

    if user_store.database_url():
        return {}
    path = data_root() / "upload_acl.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def tx_type_label(fmt: str) -> str:
    normalized = normalize_upload_format(fmt)
    labels = {
        "bos-csv": "BoS-csv",
        "lloyds-csv": "LLOYDS-csv",
        "rbs-csv": "RBS-csv",
        "natwest-csv": "Natwest-csv",
    }
    try:
        return labels[normalized]
    except KeyError as exc:
        raise ValueError(f"Not a bank CSV format: {fmt!r}") from exc


def bank_modalities() -> dict[str, str]:
    """Subfolder name → csv format (ACL file, else the UK CSV banks)."""
    raw = _acl_document().get("bank modalities")
    out: dict[str, str] = dict(_DEFAULT_BANK_MODALITIES)
    if isinstance(raw, dict):
        for folder, fmt in raw.items():
            name = str(folder or "").strip()
            if name:
                out[name] = normalize_upload_format(str(fmt or ""))
    return out


def validate_bank_folder_name(name: str) -> str:
    folder = str(name or "").strip()
    if not folder or folder in (".", ".."):
        raise ValueError("Folder name is required")
    if "/" in folder or "\\" in folder or ".." in folder:
        raise ValueError(f"Invalid folder name: {name!r}")
    return folder


def format_for_bank(bank: str) -> str:
    """Normalized csv format for a bank subfolder name (incl. ``IBAN_BoS``)."""
    folder = validate_bank_folder_name(bank)
    modalities = bank_modalities()
    candidates = [folder]
    if folder.upper().startswith("IBAN_"):
        candidates.append(folder[5:])
    for cand in candidates:
        if cand in modalities:
            return modalities[cand]
    best_name = ""
    best_fmt = ""
    for cand in candidates:
        for name, fmt in modalities.items():
            if cand == name or cand.startswith(f"{name}_") or name.startswith(f"{cand}_"):
                if len(name) > len(best_name):
                    best_name = name
                    best_fmt = fmt
    if best_fmt:
        return best_fmt
    known = ", ".join(sorted(modalities))
    raise ValueError(
        f"Folder {folder!r} does not match any bank modality (known: {known})"
    )


def format_label_for_bank(bank: str) -> str:
    """Display label (e.g. ``BoS-csv``) for a bank subfolder name."""
    return tx_type_label(format_for_bank(bank))


def default_bank_folder_for_format(fmt: str) -> str:
    normalized = normalize_upload_format(fmt)
    for folder, mapped in bank_modalities().items():
        if mapped == normalized:
            return folder
    return {
        "bos-csv": "BoS",
        "lloyds-csv": "LLOYDS",
        "rbs-csv": "RBS",
        "natwest-csv": "Natwest",
    }.get(normalized, "")


def _matches_modality_folder(name: str, modalities: dict[str, str]) -> bool:
    if name in modalities:
        return True
    return any(name == mod or name.startswith(f"{mod}_") for mod in modalities)


def detect_csv_format_from_bytes(data: bytes) -> str | None:
    """Return normalized csv format from file headers, or ``None``."""
    from app.core.bos_lloyds_csv_import import read_csv_rows_bytes as read_debit_credit
    from app.core.natwest_csv_import import read_csv_rows_bytes as read_value_balance

    try:
        read_debit_credit(data)
        return "bos-csv"
    except (ValueError, OSError, UnicodeDecodeError):
        pass
    try:
        read_value_balance(data)
        return "natwest-csv"
    except (ValueError, OSError, UnicodeDecodeError):
        pass
    return None


def infer_bank_folder_from_csv(data: bytes) -> str:
    """Guess bank subfolder from uploaded CSV headers when exactly one modality matches."""
    fmt = detect_csv_format_from_bytes(data)
    if not fmt:
        return ""
    modalities = bank_modalities()
    if fmt == "bos-csv":
        candidates = [name for name, mapped in modalities.items() if mapped in DEBIT_CREDIT_FORMATS]
    else:
        candidates = [name for name, mapped in modalities.items() if mapped in VALUE_BALANCE_FORMATS]
    if len(candidates) == 1:
        return candidates[0]
    return ""


def discover_person_banks(person: str, center: str) -> tuple[str, ...]:
    """Bank subfolder names already present under ``YYYY/`` (directory names only)."""
    from app.yearpath import list_year_names

    from app.runtime import resolve_country_for_center

    country = resolve_country_for_center(center)
    person_folder = (
        data_root() / country / center / person if country else data_root() / center / person
    )
    if not person_folder.is_dir():
        return ()
    modalities = bank_modalities()
    found: set[str] = set()
    for year in list_year_names(person_folder):
        year_path = person_folder / year
        for sub in list_year_bank_folders(year_path):
            # CSV modality folders, or PEM multi-account ``BANK_accountNumber``.
            if _matches_modality_folder(sub, modalities) or "_" in sub:
                found.add(sub)
    return tuple(sorted(found))


def person_csv_banks(person: str, center: str) -> list[str]:
    """Distinct bank subfolder names for ``person`` (from center layout)."""
    return list(discover_person_banks(person, center))


def list_year_bank_folders(year_path: Path) -> list[str]:
    """Bank subfolder names already present under ``YYYY/``."""
    if not year_path.is_dir():
        return []
    return sorted(
        child.name
        for child in year_path.iterdir()
        if child.is_dir() and not child.name.startswith(".")
    )


_YEAR_ROOT_JSON_FILES = (
    "categorized_transactions.json",
    "downloaded_transactions.json",
    "category_totals.json",
)


def pem_account_folder_name(*, aspsp: str, account_number: str) -> str:
    """Folder name ``{bank}_{accountNumber}`` for multi-account PEM downloads."""
    bank = str(aspsp or "").strip() or "BANK"
    number = str(account_number or "").strip() or "unknown"
    for ch in ('/', '\\', ':', '*', '?', '"', '<', '>', '|'):
        number = number.replace(ch, "_")
    return validate_bank_folder_name(f"{bank}_{number}")


def migrate_year_root_json_into_folder(year_path: Path, folder_name: str) -> list[str]:
    """Move flat year-root JSON stores into ``folder_name`` (first multi-account layout)."""
    folder = validate_bank_folder_name(folder_name)
    target = year_path / folder
    moved: list[str] = []
    for name in _YEAR_ROOT_JSON_FILES:
        src = year_path / name
        if not src.is_file():
            continue
        target.mkdir(parents=True, exist_ok=True)
        dest = target / name
        if dest.exists():
            continue
        src.rename(dest)
        moved.append(name)
    return moved


def person_bank_folder_options(
    person_folder: Path,
    year: str,
    *,
    person: str,
    center: str,
) -> dict[str, Any]:
    """IBANs from ``dbo.account`` for the personal account switcher."""
    del person_folder, year, center
    from app import user_store

    folders: list[str] = []
    seen: set[str] = set()
    for acc in user_store.list_accounts_for_username(person):
        iban = str(acc.get("iban") or "").strip()
        if not iban or iban in seen:
            continue
        seen.add(iban)
        folders.append(iban)

    if len(folders) <= 1:
        return {"folders": [], "multi_bank": False, "show_switcher": False}
    return {"folders": folders, "multi_bank": True, "show_switcher": True}


def _optional_text(value: Any) -> str:
    """Query/path values as text; ignore leaked FastAPI ``Query()`` objects."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if type(value).__name__ in {"Query", "FieldInfo", "Param"}:
        default = getattr(value, "default", None)
        return "" if default in (None, Ellipsis) else str(default).strip()
    return str(value).strip()


def pack_for_bank_view(
    pack: PersonPack, bank: str | None, *, center: str
) -> PersonPack:
    """Bind ``YYYY/<iban>/`` so SQL replica can filter ``dbo.account``."""
    del center
    view = _optional_text(bank)
    if not view or view.lower() == CONSOLIDATED_VIEW:
        return pack
    return replace(pack, data_dir=(pack.data_dir / view).resolve())


def person_uses_bank_subfolders(person: str, center: str) -> bool:
    """True when this pack has several accounts (dropdown / YYYY/<account>/)."""
    try:
        from app import user_store

        user = user_store.find_user(person)
        if user is not None:
            n = user.get("number_of_accounts")
            if n is not None:
                return int(n) > 1
            fmt = str(user.get("format") or "").strip().lower()
            if fmt == user_store.FORMAT_MULTIPLE:
                return True
            if fmt == user_store.FORMAT_SECRET or user_store.is_single_bank_format(fmt):
                return False
    except Exception:  # noqa: BLE001
        pass
    return len(person_csv_banks(person, center)) > 1


def bank_data_dir(person_folder: Path, year: str, *, person: str, center: str, bank: str) -> Path:
    """Directory for CSV + per-bank JSON (subfolder or flat year)."""
    year_path = person_folder / year
    if person_uses_bank_subfolders(person, center):
        return year_path / bank
    return year_path


def list_bank_subdirs(year_path: Path, *, banks: list[str]) -> list[Path]:
    out: list[Path] = []
    for name in banks:
        sub = year_path / name
        if sub.is_dir():
            out.append(sub)
    return out


def consolidate_person_year(
    person_folder: Path,
    *,
    year: str,
    person: str,
    center: str,
    categories_path: Path,
) -> dict[str, Any]:
    """Merge per-bank subfolder JSON into ``YYYY/categorized_transactions.json`` + totals."""
    from app import user_store

    if user_store.database_url():
        return {"consolidated": False, "reason": "sql"}
    year_path = person_folder / year
    if not person_uses_bank_subfolders(person, center):
        return {"consolidated": False, "reason": "single bank"}

    bank_names = list_year_bank_folders(year_path)
    subs = list_bank_subdirs(year_path, banks=bank_names)
    if not subs:
        return {"consolidated": False, "reason": "no bank subfolders"}

    from app.core.categorize import _migrate_categorized_store

    all_transactions: list[dict[str, Any]] = []
    all_accounts: list[dict[str, Any]] = []
    sources: list[str] = []

    for sub in subs:
        cat_path = sub / "categorized_transactions.json"
        tot_path = sub / "category_totals.json"
        if cat_path.is_file():
            try:
                cat = json.loads(cat_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cat = {}
            if isinstance(cat, dict):
                cat = _migrate_categorized_store(cat)
                txs = cat.get("transactions")
                if isinstance(txs, list):
                    all_transactions.extend(item for item in txs if isinstance(item, dict))
        if tot_path.is_file():
            try:
                totals = json.loads(tot_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                totals = {}
            if isinstance(totals, dict):
                accounts = totals.get("account_balances")
                if isinstance(accounts, list):
                    all_accounts.extend(item for item in accounts if isinstance(item, dict))
        sources.append(sub.name)

    name_by_code = category_name_map(categories_path)
    consolidated_totals = {
        "categories": build_category_totals(all_transactions, name_by_code),
        "account_balances": all_accounts,
    }
    consolidated_cat = _migrate_categorized_store({"transactions": all_transactions})

    cat_out = year_path / "categorized_transactions.json"
    tot_out = year_path / "category_totals.json"
    cat_out.write_text(
        json.dumps(consolidated_cat, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    tot_out.write_text(
        json.dumps(consolidated_totals, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {
        "consolidated": True,
        "banks": sources,
        "transaction_count": len(all_transactions),
        "account_count": len(all_accounts),
    }


def import_bank_csv_dir(
    data_dir: Path,
    *,
    categories_path: Path,
    fmt: str,
) -> dict[str, Any]:
    layout = csv_layout(fmt)
    label = tx_type_label(fmt)
    if layout == "debit_credit":
        from app.core.bos_lloyds_csv_import import import_person_debit_credit_csv

        return import_person_debit_credit_csv(
            data_dir=data_dir, categories_path=categories_path, tx_type=label
        )
    from app.core.natwest_csv_import import import_person_value_balance_csv

    return import_person_value_balance_csv(
        data_dir=data_dir, categories_path=categories_path, tx_type=label
    )


def refresh_bank_csv_year(
    person_folder: Path,
    *,
    year: str,
    person: str,
    center: str,
    categories_path: Path,
) -> dict[str, Any]:
    """Re-import CSV in each bank folder and consolidate when multi-bank."""
    banks = person_csv_banks(person, center)
    if not banks:
        return {"skipped": True, "reason": "no csv bank grants"}

    results: list[dict[str, Any]] = []
    if person_uses_bank_subfolders(person, center):
        year_path = person_folder / year
        for bank in list_year_bank_folders(year_path):
            try:
                fmt = format_for_bank(bank)
            except ValueError:
                continue
            sub = year_path / bank
            from app.core.bos_lloyds_csv_import import list_csv_files as list_dc
            from app.core.natwest_csv_import import list_csv_files as list_vb

            has_csv = bool(list_dc(sub) or list_vb(sub))
            if not has_csv:
                continue
            info = import_bank_csv_dir(sub, categories_path=categories_path, fmt=fmt)
            results.append({"bank": bank, **info})
        consolidation = consolidate_person_year(
            person_folder,
            year=year,
            person=person,
            center=center,
            categories_path=categories_path,
        )
        return {"banks": results, "consolidation": consolidation}

    year_path = person_folder / year
    try:
        fmt = format_for_bank(banks[0])
    except ValueError:
        return {"skipped": True, "reason": "unknown bank format"}
    info = import_bank_csv_dir(year_path, categories_path=categories_path, fmt=fmt)
    return {"banks": [{"bank": banks[0], **info}], "consolidation": {"consolidated": False}}
