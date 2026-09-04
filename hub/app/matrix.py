"""Build category × person matrix and orchestrate multi-person operations."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from app.runtime import PersonScope, bind_scope
from app.people import get_person, list_people
from app.settings import get_people, refresh_people

FOOTER_BALANCE = "saldo"
FOOTER_DATUM = "datum"


def monthly_refresh_period(
    updated_at: date | None, *, today: date | None = None
) -> tuple[date, date] | None:
    """Bank fetch window for a Refresh click, or ``None`` to skip.

    Skip when ``last_booked`` already covers today. Otherwise read from
    ``last_booked`` (or the first of the month if never updated) through today.
    """
    today = today or date.today()
    date_to = today
    if updated_at is not None and updated_at >= date_to:
        return None
    date_from = updated_at if updated_at is not None else date(date_to.year, date_to.month, 1)
    if date_from > date_to:
        return None
    return date_from, date_to


def _category_map(data: dict[str, Any]) -> dict[str, list[str]]:
    nested = data.get("categories")
    return nested if isinstance(nested, dict) else data


def load_general_file(people: list[PersonScope] | None = None) -> dict[str, Any]:
    from app.runtime import active_center, active_country
    from app.sql_catalog import categories_payload, country_for_center

    del people
    country = active_country() or country_for_center(active_center() or "") or ""
    return categories_payload(country)


def category_names(people: list[PersonScope] | None = None) -> list[str]:
    general = _category_map(load_general_file(people))
    return list(general.keys())


def table_header_terms(people: list[PersonScope] | None = None) -> dict[str, str]:
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


def person_totals(pack: PersonScope) -> dict[str, str]:
    from app import user_store
    from app.core.categorize import load_category_totals, recategorize_transactions

    with bind_scope(pack):
        try:
            totals = load_category_totals()
        except Exception:  # noqa: BLE001
            totals = {}
        if totals:
            return totals
        if user_store.database_url():
            return {}
        return recategorize_transactions()


def person_current_balance(pack: PersonScope) -> str | None:
    """Sum of ``dbo.account.balance`` for this person (one IBAN when that view is selected)."""
    from app import user_store

    accounts = user_store.list_accounts_for_username(pack.person)
    if accounts:
        view = (pack.account or "").strip()
        if view:
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
    return None


def person_updated_display(pack: PersonScope) -> str | None:
    """``dbo.account.last_booked`` as ``DD-MM-YYYY``."""
    return person_last_booked(pack)


def person_last_booked(pack: PersonScope) -> str | None:
    """``dbo.account.last_booked`` as ``DD-MM-YYYY``, or None if unset."""
    from app.sql_replica import load_bound_last_booked

    with bind_scope(pack):
        return load_bound_last_booked()


def _footer_labels(categories: list[str]) -> tuple[str, str]:
    """Catalog keys without a two-digit prefix: first = saldo, second = datum."""
    from app.core.categorize import _category_code

    uncoded = [name for name in categories if _category_code(name) is None]
    balance = uncoded[0] if uncoded else FOOTER_BALANCE
    booked = uncoded[1] if len(uncoded) > 1 else FOOTER_DATUM
    return balance, booked


def build_matrix(
    people: list[PersonScope] | None = None,
    *,
    year: str | None = None,
    bank: str | None = None,
) -> dict[str, Any]:
    from app.core.bank_csv import scope_for_account_view
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
    columns = [{"person_name": p.person_name} for p in packs]
    cells: dict[str, dict[str, str]] = {name: {} for name in category_list}
    ws = active_center() or ""
    sql_matrix = None
    if not bank:
        from app import user_store
        from app.runtime import active_country
        from app.sql_replica import load_center_year_matrix
        from app.yearpath import parse_year

        if user_store.database_url() and packs:
            y = parse_year(year) if year else parse_year(packs[0].year)
            country = active_country() or packs[0].country
            try:
                y_int = int(y)
            except (TypeError, ValueError):
                y_int = None
            if y_int is not None and country:
                sql_matrix = load_center_year_matrix(
                    center=ws or packs[0].center,
                    country=country,
                    year=y_int,
                    general_names=booking,
                )
    if sql_matrix is not None:
        totals_map, dates, balances = sql_matrix
        for pack in packs:
            key = pack.person_name
            totals = totals_map.get(key) or {}
            for name in booking:
                cells[name][pack.person_name] = _amount_for_category(totals, name)
            cells[balance_name][pack.person_name] = balances.get(key) or ""
            cells[date_name][pack.person_name] = dates.get(key) or ""
    else:
        for pack in packs:
            view_pack = scope_for_account_view(pack, bank, center=ws) if bank else pack
            try:
                totals = person_totals(view_pack)
            except Exception:  # noqa: BLE001
                totals = {}
            for name in booking:
                cells[name][pack.person_name] = _amount_for_category(totals, name)
            cells[balance_name][pack.person_name] = person_current_balance(view_pack) or ""
            cells[date_name][pack.person_name] = person_updated_display(view_pack) or ""
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
    from app.runtime import CALC_LOCK

    with CALC_LOCK:
        packs = refresh_people()
        if person_folders:
            wanted = {Path(name).name for name in person_folders}
            to_run = [p for p in packs if p.person_name in wanted]
        else:
            to_run = packs
        for pack in to_run:
            with bind_scope(pack):
                recategorize_transactions()
        return build_matrix(packs)


def recalculate_pack_from_scratch(pack: PersonScope) -> None:
    """Wipe hit/modification, then recategorize every SQL year for ``pack``."""
    from dataclasses import replace

    from app.core.categorize import recategorize_transactions
    from app.sql_catalog import years_for_person

    years = years_for_person(pack.person)
    for year in years:
        year_pack = replace(pack, year=year)
        with bind_scope(year_pack):
            recategorize_transactions(from_scratch=True)


def recalculate_all_from_scratch(person_folders: list[str] | None = None) -> dict[str, Any]:
    """From-scratch recategorize of the bound center (every year folder)."""
    from app.runtime import CALC_LOCK

    with CALC_LOCK:
        packs = refresh_people()
        if person_folders:
            wanted = {Path(name).name for name in person_folders}
            to_run = [p for p in packs if p.person_name in wanted]
        else:
            to_run = packs
        for pack in to_run:
            recalculate_pack_from_scratch(pack)
        return build_matrix(packs)


def _excel_refresh_result(pack: PersonScope) -> dict[str, Any]:
    """Recategorize SQL bookings for upload people (no year-folder scan)."""
    from app.core.categorize import recategorize_transactions
    from app.sql_catalog import list_uploaded_files
    from app.sql_replica import load_bound_transactions

    files = list_uploaded_files(pack.person)
    recategorize_transactions()
    rows = load_bound_transactions() or []
    return {
        "person_name": pack.person_name,
        "skipped": False,
        "source": "sql",
        "transaction_count": len(rows),
        "files": [item.get("file_name") or "" for item in files],
        "new_files": [],
        "file_errors": [],
    }


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
    pack: PersonScope,
    *,
    date_from: str | None,
    date_to: str | None,
    new_year: bool,
) -> tuple[dict[str, Any], list[str]]:
    from app.core.categorize import process_transactions
    from app.core.single_client import (
        enabled_bank_accounts,
        fetch_transactions,
        get_authorization_url,
        needs_consent_renewal,
    )
    from app.runtime import active_center

    warnings: list[str] = []
    if needs_consent_renewal():
        auth_url: str | None = None
        try:
            auth_url = get_authorization_url(
                center=active_center(),
                person_name=pack.person_name,
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(
                f"{pack.person_name}: "
                f"consent renewal required — could not get authorization URL ({exc})"
            )
        else:
            warnings.append(f"{pack.person_name}: consent renewal required — skipped")
        return (
            {
                "person_name": pack.person_name,
                "skipped": True,
                "reason": "needs_consent_renewal",
                "authorization_url": auth_url,
            },
            warnings,
        )

    fetched = fetch_transactions(date_from=date_from, date_to=date_to)
    accounts = enabled_bank_accounts()
    from app import user_store
    from app.enable_sql import upsert_person_accounts

    if user_store.database_url() and accounts:
        upsert_person_accounts(
            pack.person_name,
            [acc for acc in accounts if isinstance(acc, dict)],
        )

    process_transactions(fetched.transactions, new_year=bool(new_year))

    if fetched.warnings:
        for w in fetched.warnings:
            warnings.append(f"{pack.person_name}: {w}")
    if fetched.account_errors:
        for err in fetched.account_errors:
            warnings.append(f"{pack.person_name}: {err}")
    result: dict[str, Any] = {
        "person_name": pack.person_name,
        "skipped": False,
        "source": "bank",
        "transaction_count": len(fetched.transactions),
        "date_from": fetched.date_from,
        "date_to": fetched.date_to,
        "warnings": fetched.warnings,
        "account_errors": fetched.account_errors,
    }
    if new_year:
        result["new_year"] = True
    return result, warnings


def _record_account_last_booked(
    person: str, result: dict[str, Any], *, stamp: str | None = None
) -> None:
    """Persist ``dbo.account.last_booked`` after a successful refresh (date only)."""
    if result.get("skipped"):
        return
    from app import user_store

    if stamp:
        user_store.set_account_last_booked(username=person, date=stamp)
        return
    source = str(result.get("source") or "")
    if source == "bank":
        user_store.set_account_last_booked(username=person, date=result.get("date_to"))
    else:
        user_store.set_account_last_booked(username=person, date=result.get("last_date"))


def _refresh_one_person(
    pack: PersonScope,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    new_year: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    from app.core.single_client import EnableBankingError

    try:
        stamp: str | None = None
        if pack.has_pem and not new_year:
            from app import user_store

            updated = user_store.account_last_booked(pack.person_name)
            period = monthly_refresh_period(updated)
            if period is None:
                return (
                    {
                        "person_name": pack.person_name,
                        "skipped": True,
                        "reason": "updated_recently",
                        "updated_at": updated.isoformat() if updated else None,
                    },
                    [],
                )
            date_from, date_to = period[0].isoformat(), period[1].isoformat()
            stamp = date_to
        if pack.has_pem:
            result, extra = _bank_refresh_one(
                pack, date_from=date_from, date_to=date_to, new_year=new_year
            )
        else:
            excel = _excel_refresh_result(pack)
            extra = [
                f"{pack.person_name}: {err}"
                for err in (excel.get("file_errors") or [])
                if str(err).strip()
            ]
            result = excel
        _record_account_last_booked(pack.person_name, result, stamp=stamp)
        return result, extra
    except EnableBankingError as exc:
        return (
            {
                "person_name": pack.person_name,
                "skipped": True,
                "reason": str(exc),
            },
            [f"{pack.person_name}: {exc}"],
        )
    except Exception as exc:
        return (
            {
                "person_name": pack.person_name,
                "skipped": True,
                "reason": str(exc),
            },
            [f"{pack.person_name}: {exc}"],
        )


def refresh_all(
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Bank fetch for periodic-consent people only. Manual-upload people are ignored."""
    from app.runtime import CALC_LOCK

    with CALC_LOCK:
        packs = refresh_people()
        warnings: list[str] = []
        results: list[dict[str, Any]] = []

        for pack in packs:
            if not pack.has_pem:
                continue
            with bind_scope(pack):
                result, extra = _refresh_one_person(
                    pack, date_from=date_from, date_to=date_to, new_year=False
                )
                results.append(result)
                warnings.extend(extra)

        matrix = build_matrix(packs)
        return {"matrix": matrix, "results": results, "warnings": warnings}


def refresh_person(
    person_name: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    new_year: bool = False,
) -> dict[str, Any]:
    """Refresh one person (bank fetch or Excel conversion)."""
    from app.runtime import CALC_LOCK

    with CALC_LOCK:
        packs = refresh_people()
        pack = get_person(person_name)
        warnings: list[str] = []
        results: list[dict[str, Any]] = []

        with bind_scope(pack):
            result, extra = _refresh_one_person(
                pack, date_from=date_from, date_to=date_to, new_year=new_year
            )
            results.append(result)
            warnings.extend(extra)

        matrix = build_matrix(packs)
        return {"matrix": matrix, "results": results, "warnings": warnings}


def save_general_terms(category_name: str, terms: list[str]) -> list[str]:
    from app.core.categorize import _cleaned_terms, _save_general_category_terms

    cleaned = _cleaned_terms(terms)
    _save_general_category_terms(category_name, cleaned)
    return cleaned


def save_personal_terms(person_name: str, category_name: str, terms: list[str]) -> list[str]:
    from app.core.categorize import _cleaned_terms, _save_personal_category_terms

    pack = get_person(person_name)
    with bind_scope(pack):
        cleaned = _cleaned_terms(terms)
        _save_personal_category_terms(category_name, cleaned)
        return cleaned
