"""Build category × person matrix and orchestrate multi-person operations."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.paths import PersonPack, bind_person
from app.people import get_person, list_people
from app.settings import get_people, refresh_people

FOOTER_BALANCE = "saldo"
FOOTER_DATUM = "datum"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _category_map(data: dict[str, Any]) -> dict[str, list[str]]:
    nested = data.get("categories")
    return nested if isinstance(nested, dict) else data


def general_categories_source(people: list[PersonPack] | None = None) -> Path:
    from app.paths import shared_categories_path

    path = shared_categories_path()
    if path.is_file():
        return path
    raise FileNotFoundError(
        f"No categories.json found beside the admin root ({path})."
    )


def load_general_file(people: list[PersonPack] | None = None) -> dict[str, Any]:
    from app.paths import shared_categories_path
    from app.runtime import active_center, active_country
    from app.sql_catalog import categories_payload, country_for_center

    path = shared_categories_path()
    if path.is_file():
        data = _read_json(path)
        return data if isinstance(data, dict) else {}
    country = active_country() or country_for_center(active_center() or "") or ""
    return categories_payload(country)


def category_names(people: list[PersonPack] | None = None) -> list[str]:
    general = _category_map(load_general_file(people))
    return list(general.keys())


def sync_general_categories(payload: dict[str, Any], people: list[PersonPack] | None = None) -> None:
    """Write the shared ``categories.json`` at the boekhouding deploy root."""
    from app.paths import shared_categories_path

    _write_json(shared_categories_path(), payload)


def table_header_terms(people: list[PersonPack] | None = None) -> dict[str, str]:
    """English key → display label from ``categories.json`` ``table_header_terms``."""
    raw = load_general_file(people).get("table_header_terms")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key).strip()
        label = str(value).strip()
        if name and label:
            out[name] = label
    return out


def _amount_for_category(totals: dict[str, str], catalog_name: str) -> str:
    """Look up a totals cell by catalog label, or by the two-digit local code.

    UK ``categories.json`` uses English labels; existing ``category_totals.json``
    still has Dutch keys. Codes (08, 12, 18, …) are the join.
    """
    from app.core.categorize import _category_code

    if catalog_name in totals:
        return str(totals[catalog_name])
    code = _category_code(catalog_name)
    if code is None:
        return "0.00"
    for name, amount in totals.items():
        if _category_code(name) == code:
            return str(amount)
    return "0.00"


def person_totals(pack: PersonPack) -> dict[str, str]:
    from app.core.categorize import load_category_totals, recategorize_transactions

    with bind_person(pack):
        totals = load_category_totals()
        if not totals:
            totals = recategorize_transactions()
        return totals


def person_current_balance(pack: PersonPack) -> str | None:
    """Sum of ``dbo.account.balance`` for this person (one IBAN when that view is selected)."""
    from app import user_store

    accounts = user_store.list_accounts_for_username(pack.folder_name)
    if accounts:
        view = pack.data_dir.name
        if view != pack.year:
            compact = view.replace(" ", "")
            accounts = [
                acc
                for acc in accounts
                if str(acc.get("iban") or "").replace(" ", "") == compact
            ]
        cents = 0
        found = False
        for acc in accounts:
            text = str(acc.get("balance") or "").strip()
            if not text:
                continue
            try:
                cents += round(float(text) * 100)
            except ValueError:
                continue
            found = True
        if found:
            return f"{cents / 100:.2f}"
        return None

    from app.core.categorize import _load_json_object
    import app.paths as paths

    with bind_person(pack):
        data = _load_json_object(paths.CATEGORY_TOTALS_PATH)
    json_accounts = data.get("account_balances")
    if not isinstance(json_accounts, list) or not json_accounts:
        return None
    cents = 0
    found = False
    for acc in json_accounts:
        if not isinstance(acc, dict):
            continue
        text = str(acc.get("balance") or "").strip()
        if not text:
            continue
        try:
            cents += round(float(text) * 100)
        except ValueError:
            continue
        found = True
    if not found:
        return None
    return f"{cents / 100:.2f}"


def person_last_booked(pack: PersonPack) -> str | None:
    """Latest transaction ``date`` as ``DD-MM-YYYY``, or None if none."""
    from app.core.categorize import _load_categorized_store
    from app.user_store import latest_transaction_date

    with bind_person(pack):
        data = _load_categorized_store()
    txs = data.get("transactions") if isinstance(data, dict) else None
    if not isinstance(txs, list):
        return None
    iso = latest_transaction_date(txs)
    if not iso or len(iso) < 10:
        return None
    return f"{iso[8:10]}-{iso[5:7]}-{iso[0:4]}"


def _footer_labels(categories: list[str]) -> tuple[str, str]:
    """Catalog keys without a two-digit prefix: first = saldo, second = datum."""
    from app.core.categorize import _category_code

    uncoded = [name for name in categories if _category_code(name) is None]
    balance = uncoded[0] if uncoded else FOOTER_BALANCE
    booked = uncoded[1] if len(uncoded) > 1 else FOOTER_DATUM
    return balance, booked


def build_matrix(
    people: list[PersonPack] | None = None,
    *,
    year: str | None = None,
    bank: str | None = None,
) -> dict[str, Any]:
    from app.core.bank_csv import pack_for_bank_view
    from app.runtime import active_center

    if people is not None:
        packs = people
    elif year is not None:
        # Year-specific matrix: include only persons with that year folder.
        packs = list_people(year=year)
    else:
        packs = get_people()
    from app.core.categorize import _category_code

    categories = category_names(packs)
    balance_name, date_name = _footer_labels(categories)
    booking = [name for name in categories if _category_code(name) is not None]
    category_list = booking + [balance_name, date_name]
    columns = [{"short": p.short, "folder": p.folder_name} for p in packs]
    cells: dict[str, dict[str, str]] = {name: {} for name in category_list}
    ws = active_center() or ""
    for pack in packs:
        view_pack = pack_for_bank_view(pack, bank, center=ws) if bank else pack
        totals = person_totals(view_pack)
        for name in booking:
            cells[name][pack.short] = _amount_for_category(totals, name)
        cells[balance_name][pack.short] = person_current_balance(view_pack) or ""
        cells[date_name][pack.short] = person_last_booked(view_pack) or ""
    payload: dict[str, Any] = {
        "categories": category_list,
        "people": columns,
        "cells": cells,
        "footers": {"balance": balance_name, "last_booked": date_name},
        "table_header_terms": table_header_terms(packs),
    }
    ws = active_center()
    if ws:
        payload["center"] = ws
    return payload


def recalculate_all(person_folders: list[str] | None = None) -> dict[str, Any]:
    """Recategorize people; when ``person_folders`` is set, only those packs are rewritten."""
    from app.core.categorize import recategorize_transactions
    from app.paths import CALC_LOCK

    with CALC_LOCK:
        packs = refresh_people()
        if person_folders:
            wanted = {Path(name).name for name in person_folders}
            to_run = [p for p in packs if p.folder_name in wanted]
        else:
            to_run = packs
        for pack in to_run:
            # Recategorize anyone with year data — not only Enable Banking (.pem) packs.
            if not pack.categorized_path.is_file() and not pack.totals_path.is_file():
                continue
            with bind_person(pack):
                recategorize_transactions()
        return build_matrix(packs)


def recalculate_pack_from_scratch(pack: PersonPack) -> None:
    """Wipe hit/modification, then recategorize every year (and bank folder) for ``pack``."""
    from dataclasses import replace

    from app.core.bank_csv import list_year_bank_folders
    from app.core.categorize import recategorize_transactions
    from app.yearpath import list_year_names

    for year in list_year_names(pack.folder):
        year_path = pack.folder / year
        targets = [year_path]
        for bank in list_year_bank_folders(year_path):
            targets.append(year_path / bank)
        for data_dir in targets:
            if not (data_dir / "categorized_transactions.json").is_file():
                continue
            year_pack = replace(pack, data_dir=data_dir.resolve(), year=year)
            with bind_person(year_pack):
                recategorize_transactions(from_scratch=True)


def recalculate_all_from_scratch(person_folders: list[str] | None = None) -> dict[str, Any]:
    """From-scratch recategorize of the bound center (every year folder)."""
    from app.paths import CALC_LOCK

    with CALC_LOCK:
        packs = refresh_people()
        if person_folders:
            wanted = {Path(name).name for name in person_folders}
            to_run = [p for p in packs if p.folder_name in wanted]
        else:
            to_run = packs
        for pack in to_run:
            recalculate_pack_from_scratch(pack)
        return build_matrix(packs)


def _excel_refresh_result(pack: PersonPack) -> dict[str, Any]:
    from app.core.bank_csv import person_csv_banks, refresh_bank_csv_year
    from app.core.excel_import import import_person_excel, list_xlsx_files
    from app.paths import shared_categories_path

    categories_path = shared_categories_path()
    center = pack.folder.parent.name
    person = pack.folder_name
    banks = person_csv_banks(person, center)
    if banks:
        refreshed = refresh_bank_csv_year(
            pack.folder,
            year=pack.year,
            person=person,
            center=center,
            categories_path=categories_path,
        )
        if refreshed.get("skipped"):
            return {
                "short": pack.short,
                "folder": pack.folder_name,
                "skipped": True,
                "source": "bank-csv",
                "reason": refreshed.get("reason") or "no csv bank data",
            }
        bank_results = refreshed.get("banks") or []
        consolidation = refreshed.get("consolidation") or {}
        total_tx = sum(int(item.get("transaction_count") or 0) for item in bank_results)
        all_files: list[str] = []
        all_new: list[str] = []
        all_errors: list[str] = []
        last_dates: list[str] = []
        for item in bank_results:
            all_files.extend(item.get("files") or [])
            all_new.extend(item.get("new_files") or [])
            all_errors.extend(item.get("file_errors") or [])
            ld = str(item.get("last_date") or "").strip()
            if ld:
                last_dates.append(ld)
        from dataclasses import replace as _replace

        from app.core.bank_csv import list_year_bank_folders, person_uses_bank_subfolders
        from app.core.categorize import finalize_imported_bookings

        year_path = pack.folder / pack.year
        if person_uses_bank_subfolders(person, center):
            for bank in list_year_bank_folders(year_path):
                with bind_person(_replace(pack, data_dir=(year_path / bank).resolve())):
                    finalize_imported_bookings()
        finalize_imported_bookings()
        return {
            "short": pack.short,
            "folder": pack.folder_name,
            "skipped": False,
            "source": "bank-csv",
            "transaction_count": total_tx,
            "banks": [item.get("bank") for item in bank_results if item.get("bank")],
            "consolidated": bool(consolidation.get("consolidated")),
            "files": all_files,
            "new_files": all_new,
            "file_errors": all_errors,
            "last_date": max(last_dates) if last_dates else None,
        }
    if not list_xlsx_files(pack.data_dir):
        return {
            "short": pack.short,
            "folder": pack.folder_name,
            "skipped": True,
            "source": "excel",
            "reason": "no xlsx or csv files",
        }
    info = import_person_excel(data_dir=pack.data_dir, categories_path=categories_path)
    from app.core.categorize import finalize_imported_bookings

    finalize_imported_bookings()
    return {
        "short": pack.short,
        "folder": pack.folder_name,
        "skipped": False,
        "source": "excel",
        "transaction_count": info.get("transaction_count", 0),
        "files": info.get("files") or [],
        "new_files": info.get("new_files") or [],
        "balance_updated": bool(info.get("balance_updated")),
        "balance": info.get("balance"),
        "file_errors": info.get("file_errors") or [],
        "last_date": info.get("last_date"),
    }


def _narrow_totals_to_account(uid: str) -> None:
    """Keep only this account's balance row in the bound category_totals.json."""
    from app import paths as path_mod

    path = path_mod.CATEGORY_TOTALS_PATH
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    balances = data.get("account_balances")
    if not isinstance(balances, list):
        return
    needle = str(uid or "")
    data["account_balances"] = [
        row
        for row in balances
        if isinstance(row, dict) and str(row.get("uid") or "") == needle
    ]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _txs_for_account(
    transactions: list[dict[str, Any]],
    *,
    uid: str,
    account_index: int,
) -> list[dict[str, Any]]:
    needle = str(uid or "")
    by_uid = [
        tx
        for tx in transactions
        if isinstance(tx, dict) and str(tx.get("_account_uid") or "") == needle
    ]
    if by_uid or any(
        isinstance(tx, dict) and str(tx.get("_account_uid") or "").strip() for tx in transactions
    ):
        return by_uid
    out: list[dict[str, Any]] = []
    for tx in transactions:
        if not isinstance(tx, dict):
            continue
        try:
            idx = int(tx.get("_account_index", -1))
        except (TypeError, ValueError):
            continue
        if idx == account_index:
            out.append(tx)
    return out


def _bank_refresh_one(
    pack: PersonPack,
    *,
    date_from: str | None,
    date_to: str | None,
    new_year: bool,
) -> tuple[dict[str, Any], list[str]]:
    from dataclasses import replace

    from app.core.bank_csv import (
        consolidate_person_year,
        list_year_bank_folders,
        migrate_year_root_json_into_folder,
        pem_account_folder_name,
    )
    from app.core.categorize import process_transactions
    from app.core.single_client import (
        account_index_by_uid,
        enabled_bank_accounts,
        fetch_transactions,
        get_authorization_url,
        needs_consent_renewal,
    )
    from app.paths import apply_person, shared_categories_path
    from app.runtime import active_center

    warnings: list[str] = []
    if needs_consent_renewal():
        auth_url: str | None = None
        try:
            auth_url = get_authorization_url(
                center=active_center(),
                person_short=pack.short,
                folder=pack.folder_name,
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(
                f"{pack.short} ({pack.folder_name}): "
                f"consent renewal required — could not get authorization URL ({exc})"
            )
        else:
            warnings.append(
                f"{pack.short} ({pack.folder_name}): consent renewal required — skipped"
            )
        return (
            {
                "short": pack.short,
                "folder": pack.folder_name,
                "skipped": True,
                "reason": "needs_consent_renewal",
                "authorization_url": auth_url,
            },
            warnings,
        )

    fetched = fetch_transactions(date_from=date_from, date_to=date_to)
    accounts = enabled_bank_accounts()
    account_folders: list[str] = []
    from app.sql_replica import ensure_bound_accounts

    ensure_bound_accounts(
        [
            {
                "iban": str(acc.get("iban") or "").strip(),
                "account_name": str(acc.get("name") or acc.get("iban") or "account"),
                "balance": acc.get("balance") or "0",
                "format": "secret",
            }
            for acc in accounts
            if isinstance(acc, dict)
        ],
        default_format="secret",
    )

    if len(accounts) <= 1:
        process_transactions(fetched.transactions, new_year=bool(new_year))
    else:
        year_path = pack.data_dir
        index_by_uid = account_index_by_uid()
        targets: list[tuple[dict[str, Any], str, int]] = []
        for acc in accounts:
            folder = pem_account_folder_name(
                aspsp=str(acc.get("aspsp") or ""),
                account_number=str(acc.get("iban") or acc.get("name") or ""),
            )
            uid = str(acc.get("uid") or "")
            targets.append((acc, folder, index_by_uid.get(uid, -1)))
            account_folders.append(folder)

        if not list_year_bank_folders(year_path):
            migrate_year_root_json_into_folder(year_path, targets[0][1])

        try:
            from app import user_store

            user_store.set_user_format(
                username=pack.folder_name, format=user_store.FORMAT_MULTIPLE
            )
        except Exception:  # noqa: BLE001
            pass

        for acc, folder, account_index in targets:
            sub = (year_path / folder).resolve()
            sub.mkdir(parents=True, exist_ok=True)
            apply_person(replace(pack, data_dir=sub))
            batch = _txs_for_account(
                fetched.transactions,
                uid=str(acc.get("uid") or ""),
                account_index=account_index,
            )
            process_transactions(batch, new_year=bool(new_year))
            _narrow_totals_to_account(str(acc.get("uid") or ""))

        consolidate_person_year(
            pack.folder,
            year=pack.year,
            person=pack.folder_name,
            center=active_center(),
            categories_path=shared_categories_path(),
        )
        apply_person(pack)

    if fetched.warnings:
        for w in fetched.warnings:
            warnings.append(f"{pack.short}: {w}")
    if fetched.account_errors:
        for err in fetched.account_errors:
            warnings.append(f"{pack.short}: {err}")
    result: dict[str, Any] = {
        "short": pack.short,
        "folder": pack.folder_name,
        "skipped": False,
        "source": "bank",
        "transaction_count": len(fetched.transactions),
        "date_from": fetched.date_from,
        "date_to": fetched.date_to,
        "warnings": fetched.warnings,
        "account_errors": fetched.account_errors,
    }
    if account_folders:
        result["account_folders"] = account_folders
    if new_year:
        result["new_year"] = True
    return result, warnings


def _record_user_updated_at(person: str, result: dict[str, Any]) -> None:
    """Persist ``users.updated_at`` after a successful refresh (date only)."""
    if result.get("skipped"):
        return
    from app import user_store

    source = str(result.get("source") or "")
    if source == "bank":
        user_store.set_user_updated_at(username=person, date=result.get("date_to"))
    else:
        user_store.set_user_updated_at(username=person, date=result.get("last_date"))


def _refresh_one_person(
    pack: PersonPack,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    new_year: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    from app.core.single_client import EnableBankingError

    try:
        if pack.has_secret_folder:
            result, extra = _bank_refresh_one(
                pack, date_from=date_from, date_to=date_to, new_year=new_year
            )
        else:
            excel = _excel_refresh_result(pack)
            extra = [
                f"{pack.short} ({pack.folder_name}): {err}"
                for err in (excel.get("file_errors") or [])
                if str(err).strip()
            ]
            result = excel
        _record_user_updated_at(pack.folder_name, result)
        return result, extra
    except EnableBankingError as exc:
        return (
            {
                "short": pack.short,
                "folder": pack.folder_name,
                "skipped": True,
                "reason": str(exc),
            },
            [f"{pack.short} ({pack.folder_name}): {exc}"],
        )
    except Exception as exc:
        return (
            {
                "short": pack.short,
                "folder": pack.folder_name,
                "skipped": True,
                "reason": str(exc),
            },
            [f"{pack.short} ({pack.folder_name}): {exc}"],
        )


def refresh_all(
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Bank fetch for secret packs; Excel conversion for everyone else."""
    from app.paths import CALC_LOCK

    with CALC_LOCK:
        packs = refresh_people()
        warnings: list[str] = []
        results: list[dict[str, Any]] = []

        for pack in packs:
            with bind_person(pack):
                result, extra = _refresh_one_person(
                    pack, date_from=date_from, date_to=date_to, new_year=False
                )
                results.append(result)
                warnings.extend(extra)

        matrix = build_matrix(packs)
        return {"matrix": matrix, "results": results, "warnings": warnings}


def refresh_person(
    short: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    new_year: bool = False,
) -> dict[str, Any]:
    """Refresh one person (bank fetch or Excel conversion)."""
    from app.paths import CALC_LOCK

    with CALC_LOCK:
        packs = refresh_people()
        pack = get_person(short)
        warnings: list[str] = []
        results: list[dict[str, Any]] = []

        with bind_person(pack):
            result, extra = _refresh_one_person(
                pack, date_from=date_from, date_to=date_to, new_year=new_year
            )
            results.append(result)
            warnings.extend(extra)

        matrix = build_matrix(packs)
        return {"matrix": matrix, "results": results, "warnings": warnings}


def save_general_terms(category_name: str, terms: list[str]) -> list[str]:
    from app.core.categorize import _cleaned_terms, _category_map

    packs = get_people()
    original = _read_json(general_categories_source(packs))
    if not isinstance(original, dict):
        original = {}
    cleaned = _cleaned_terms(terms)
    if isinstance(original.get("categories"), dict):
        original["categories"][category_name] = cleaned
    else:
        categories = _category_map(original)
        categories[category_name] = cleaned
        original = categories
    sync_general_categories(original, packs)
    return cleaned


def save_personal_terms(short: str, category_name: str, terms: list[str]) -> list[str]:
    from app.core.categorize import _cleaned_terms, _save_personal_category_terms

    pack = get_person(short)
    with bind_person(pack):
        cleaned = _cleaned_terms(terms)
        _save_personal_category_terms(category_name, cleaned)
        return cleaned
