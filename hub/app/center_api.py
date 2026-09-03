"""High-level center UI operations (hub-only data; no client copies)."""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app import store
from app.runtime import CALC_LOCK
from app.yearpath import current_year


def _clean_ws(center: str) -> str:
    ws = center.strip().replace("\\", "/").strip("/")
    if not ws or ".." in ws.split("/") or ws.startswith("/"):
        raise ValueError(f"Invalid center: {center!r}")
    return ws


@contextmanager
def _center_scope(center: str) -> Iterator[str]:
    """Bind active center + people list under CALC_LOCK for the whole request.

    Path globals and ``_active_center`` are process-wide; uvicorn runs sync
    routes in a threadpool, so concurrent client requests must not interleave.
    """
    from app.runtime import request_country, set_active_center

    ws = _clean_ws(center)
    with CALC_LOCK:
        from app.sql_catalog import coerce_center, country_for_center

        ws = coerce_center(ws)
        country = request_country() or country_for_center(ws)
        set_active_center(ws, country=country)
        from app.settings import init_app

        init_app()
        yield ws


def _has_secrets(center: str) -> bool:
    from app.enable_sql import center_has_pem

    return center_has_pem(center)


def _people_payload(people: list[Any]) -> list[dict[str, str]]:
    return [{"person_name": p.person_name} for p in people]


def _with_person(rows: list[dict[str, Any]], person_name: str) -> list[dict[str, Any]]:
    """Stamp each row with the bound person name (API identity; not written to disk)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["person"] = person_name
        out.append(item)
    return out


def capabilities(center: str) -> dict[str, Any]:
    with _center_scope(center) as ws:
        from app.settings import get_people

        people = get_people()
        return {
            "ok": True,
            "center": ws,
            "has_secrets": _has_secrets(ws),
            "people": _people_payload(people),
        }


def people(center: str) -> dict[str, Any]:
    caps = capabilities(center)
    return {"center": caps["center"], "people": caps["people"]}


def matrix(center: str, *, year: str | None = None, bank: str | None = None) -> dict[str, Any]:
    with _center_scope(center) as ws:
        from app.matrix import build_matrix

        payload = build_matrix(year=year, bank=bank)
        payload["center"] = ws
        if bank:
            payload["bank_view"] = bank
        return payload


def person_banks(center: str, person_name: str, *, year: str | None = None) -> dict[str, Any]:
    with _center_scope(center) as ws:
        from app.core.bank_csv import _optional_text, person_bank_folder_options
        from app.people import get_person

        person_name = person_name.strip()
        year_name = _optional_text(year) or current_year()
        try:
            pack = get_person(person_name, year=year_name)
            person_name = pack.person
            year_name = pack.year
        except KeyError:
            pass
        opts = person_bank_folder_options(person=person_name)
        token = ""
        first_download = False
        needs_initial_authorization = False
        try:
            from app import enable_sql, user_store

            token = user_store.upload_token_by_person_center().get(
                (person_name, ws), ""
            ) or ""
            if user_store.database_url() and person_name:
                has_credentials = enable_sql.person_has_pem_light(person_name)
                consent_active = enable_sql.person_consent_ready(person_name) is True
                has_downloads = enable_sql.person_has_transactions(person_name)
                first_download = bool(consent_active) and not has_downloads
                needs_initial_authorization = (
                    bool(has_credentials) and not consent_active and not has_downloads
                )
        except Exception:  # noqa: BLE001
            token = token or ""
        return {
            "center": ws,
            "person": person_name,
            "year": year_name,
            "upload_token": token,
            "first_download": first_download,
            "needs_initial_authorization": needs_initial_authorization,
            **opts,
        }


def transactions(
    center: str,
    person_name: str,
    category_name: str,
    *,
    year: str | None = None,
    bank: str | None = None,
) -> dict[str, Any]:
    with _center_scope(center) as ws:
        from app.core.bank_csv import _optional_text, scope_for_account_view
        from app.core.categorize import (
            _categories_file,
            category_code_set,
            modification_style_ids,
            remainder_category_name,
            terms_for_category,
            transaction_display_column_keys as column_keys,
            transactions_for_category as load_transactions,
        )
        from app.runtime import bind_scope
        from app.people import get_person

        pack = get_person(person_name, year=_optional_text(year) or None)
        pack = scope_for_account_view(pack, bank, center=ws)
        with bind_scope(pack):
            rows = load_transactions(category_name)
            cat_data = _categories_file()
            description_modified_ids, category_modified_ids = modification_style_ids()
            header_terms = cat_data.get("table_header_terms") if isinstance(cat_data, dict) else {}
            return {
                "center": ws,
                "person": pack.person_name,
                "category": category_name,
                "columns": column_keys(rows),
                "transactions": _with_person(rows, pack.person_name),
                "keywords": terms_for_category(category_name),
                "description_modified_ids": description_modified_ids,
                "category_modified_ids": category_modified_ids,
                "abbreviations": cat_data.get("abbreviations", {})
                if isinstance(cat_data, dict)
                else {},
                "table_header_terms": header_terms if isinstance(header_terms, dict) else {},
                "valid_category_codes": sorted(category_code_set()),
                "remainder_category": remainder_category_name(),
            }


def record_modification(
    center: str,
    person_name: str,
    transaction: dict[str, Any],
    *,
    source: str = "local",
) -> dict[str, Any]:
    with _center_scope(center) as ws:
        from app.core.categorize import record_modification as _record
        from app.runtime import bind_scope
        from app.people import get_person

        pack = get_person(person_name)
        with bind_scope(pack):
            modified = _record(transaction)
        from app import user_store

        if user_store.database_url():
            from app.matrix import build_matrix

            modified_out = dict(modified) if isinstance(modified, dict) else modified
            if isinstance(modified_out, dict):
                modified_out["person"] = pack.person_name
            return {
                "center": ws,
                "person": pack.person_name,
                "transaction": modified_out,
                "affected_files": [],
                "matrix": build_matrix(year=pack.year),
            }
        rel = store.person_year_rel(pack.person_name, store.CATEGORIZED, year=pack.year)
        path = store.resolve_file_path(ws, rel)
        content = json.loads(path.read_text(encoding="utf-8"))
        store.put_file(
            ws,
            rel,
            content,
            source=source,
            skip_recalc=True,
            skip_event=True,
        )
        totals_rel = store.person_year_rel(
            pack.person_name, store.CATEGORY_TOTALS, year=pack.year
        )
        totals_path = store.resolve_file_path(ws, totals_rel)
        inputs = [rel]
        if totals_path.is_file():
            store.put_file(
                ws,
                totals_rel,
                json.loads(totals_path.read_text(encoding="utf-8")),
                source=source,
                skip_recalc=True,
                skip_event=True,
            )
            inputs.append(totals_rel)
        result = store.mutate_and_publish(ws, inputs, source=source, announce=False)
        modified_out = dict(modified) if isinstance(modified, dict) else modified
        if isinstance(modified_out, dict):
            modified_out["person"] = pack.person_name
        return {
            "center": ws,
            "person": pack.person_name,
            "transaction": modified_out,
            "affected_files": result.get("affected_files") or [],
            "matrix": result.get("matrix"),
        }


def transaction_split(
    center: str,
    person_name: str,
    *,
    source_id: str,
    year: str | None = None,
    bank: str | None = None,
) -> dict[str, Any]:
    with _center_scope(center) as ws:
        from app.core.bank_csv import _optional_text, scope_for_account_view
        from app.core.categorize import load_transaction_split
        from app.runtime import bind_scope
        from app.people import get_person

        pack = get_person(person_name, year=_optional_text(year) or None)
        pack = scope_for_account_view(pack, bank, center=ws)
        with bind_scope(pack):
            payload = load_transaction_split(source_id)
        return {
            "center": ws,
            "person": pack.person_name,
            "year": pack.year,
            **payload,
        }


def save_transaction_split(
    center: str,
    person_name: str,
    *,
    source_id: str,
    description: str,
    lines: list[dict[str, Any]],
    year: str | None = None,
    bank: str | None = None,
) -> dict[str, Any]:
    with _center_scope(center) as ws:
        from app.core.bank_csv import _optional_text, scope_for_account_view
        from app.core.categorize import save_transaction_split as _save
        from app.runtime import bind_scope
        from app.people import get_person

        pack = get_person(person_name, year=_optional_text(year) or None)
        pack = scope_for_account_view(pack, bank, center=ws)
        with bind_scope(pack):
            payload = _save(source_id, description=description, lines=lines)
        return {
            "center": ws,
            "person": pack.person_name,
            "year": pack.year,
            **payload,
        }


def settings(center: str) -> dict[str, Any]:
    with _center_scope(center) as ws:
        from app import user_store
        from app.core.categorize import (
            _category_map,
            _personal_category_map,
            category_code_set,
            remainder_category_name,
            type_rules_payload,
        )
        from app.matrix import category_names, load_general_file, table_header_terms
        from app.runtime import bind_scope
        from app.settings import get_people

        if user_store.database_url():
            from app.sql_catalog import clear_catalog_cache

            clear_catalog_cache()
        people_list = get_people()
        general_file = load_general_file(people_list)
        general = _category_map(general_file)
        personal: dict[str, dict[str, list[str]]] = {}
        typerules: list[dict[str, str]] = []
        codes: list[int] = []
        remainder = ""
        for pack in people_list:
            with bind_scope(pack):
                personal[pack.person_name] = _personal_category_map()
                if not typerules:
                    typerules = type_rules_payload()
                if not codes:
                    codes = sorted(category_code_set())
                    remainder = remainder_category_name()
        return {
            "center": ws,
            "categories": category_names(people_list),
            "people": _people_payload(people_list),
            "general": general,
            "personal": personal,
            "valid_category_codes": codes,
            "remainder_category": remainder,
            "typerules": typerules,
            "table_header_terms": table_header_terms(people_list),
        }


def catalog(center: str) -> dict[str, Any]:
    with _center_scope(center) as ws:
        from app.runtime import active_country
        from app.sql_catalog import booking_categories_payload, country_for_center

        country = active_country() or country_for_center(ws) or ""
        payload = booking_categories_payload(country)
        payload["center"] = ws
        return payload


def update_catalog(center: str, categories: list[dict[str, Any]]) -> dict[str, Any]:
    with _center_scope(center) as ws:
        from app.runtime import active_country
        from app.sql_catalog import country_for_center, save_booking_categories

        country = active_country() or country_for_center(ws) or ""
        payload = save_booking_categories(country, categories)
        payload["center"] = ws
        return payload


def update_settings(
    center: str,
    group: str,
    category_name: str,
    terms: list[str],
    *,
    source: str = "local",
) -> dict[str, Any]:
    """Save terms, then announce + iRCfT (lock released before the scan)."""
    from app import user_store
    from app.core.categorize import (
        _categories_file,
        _category_map,
        _personal_category_map,
        term_list_diff,
    )
    from app.matrix import build_matrix, save_general_terms, save_personal_terms
    from app.people import get_person
    from app.runtime import bind_scope

    sql = bool(user_store.database_url())
    with _center_scope(center) as ws:
        if group == "general":
            old_terms = list(_category_map(_categories_file()).get(category_name, []) or [])
            cleaned = save_general_terms(category_name, terms)
            rel = store.SHARED_CATEGORIES
            content: Any = None if sql else _categories_file()
            recalc_all = True
            group_name = "general"
            personal = False
        else:
            pack = get_person(group)
            with bind_scope(pack):
                old_terms = list(_personal_category_map().get(category_name, []) or [])
            cleaned = save_personal_terms(pack.person_name, category_name, terms)
            rel = store.person_secret_rel(pack.person_name, store.PERSONAL_CATEGORIES)
            content = None
            if not sql:
                path = store.resolve_file_path(ws, rel)
                if path.is_file():
                    content = json.loads(path.read_text(encoding="utf-8"))
                else:
                    content = {}
            recalc_all = False
            group_name = pack.person_name
            personal = True

    added, removed = term_list_diff(old_terms, cleaned)
    if content is not None:
        store.put_file(
            ws,
            rel,
            content,
            source=source,
            skip_recalc=True,
            skip_event=True,
        )
    if added or removed:
        result = store.mutate_and_ircft(
            ws,
            [rel],
            source=source,
            recalc_all_centers=recalc_all,
            added=added,
            removed=removed,
            personal=personal,
            category_name=category_name,
        )
    else:
        result = {"affected_files": [rel], "matrix": None}
    with _center_scope(ws):
        matrix = result.get("matrix") or {**build_matrix(), "center": ws}
    return {
        "center": ws,
        "group": group_name,
        "category": category_name,
        "terms": cleaned,
        "matrix": matrix,
        "affected_files": result.get("affected_files") or [],
    }


def add_term(
    center: str,
    *,
    category_name: str,
    term: str,
    general: bool,
    person: str | None = None,
    source: str = "local",
) -> dict[str, Any]:
    with _center_scope(center) as ws:
        from app import user_store
        from app.core.categorize import (
            _categories_file,
            _category_map,
            _personal_category_map,
            append_category_term,
            term_list_diff,
        )
        from app.matrix import (
            build_matrix,
        )
        from app.runtime import bind_scope
        from app.people import get_person
        from app.settings import get_people

        sql = bool(user_store.database_url())
        people_list = get_people()
        if general:
            pack = people_list[0]
            with bind_scope(pack):
                old_terms = list(
                    _category_map(_categories_file()).get(category_name, []) or []
                )
                terms = append_category_term(
                    category_name,
                    term,
                    group="general",
                    person=pack.person_name,
                )
                after_terms = list(
                    _category_map(_categories_file()).get(category_name, []) or []
                )
            added, removed = term_list_diff(old_terms, after_terms)
            if not sql:
                store.put_file(
                    ws,
                    store.SHARED_CATEGORIES,
                    _categories_file(),
                    source=source,
                    skip_recalc=True,
                    skip_event=True,
                )
            if added or removed:
                result = store.mutate_and_ircft(
                    ws,
                    [store.SHARED_CATEGORIES],
                    source=source,
                    recalc_all_centers=True,
                    added=added,
                    removed=removed,
                    personal=False,
                    category_name=category_name,
                )
            else:
                result = {"affected_files": [store.SHARED_CATEGORIES], "matrix": None}
            return {
                "center": ws,
                "group": "general",
                "category": category_name,
                "term": term,
                "terms": terms,
                "matrix": result.get("matrix") or {**build_matrix(), "center": ws},
                "affected_files": result.get("affected_files") or [],
            }

        person_name = (person or "").strip()
        if not person_name:
            raise ValueError("person is required when general=false")
        pack = get_person(person_name)
        with bind_scope(pack):
            old_terms = list(_personal_category_map().get(category_name, []) or [])
            terms = append_category_term(
                category_name,
                term,
                group=pack.person_name,
                person=pack.person_name,
            )
            after_terms = list(_personal_category_map().get(category_name, []) or [])
        added, removed = term_list_diff(old_terms, after_terms)
        rel = store.person_secret_rel(pack.person_name, store.PERSONAL_CATEGORIES)
        if not sql:
            path = store.resolve_file_path(ws, rel)
            content = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            store.put_file(
                ws,
                rel,
                content,
                source=source,
                skip_recalc=True,
                skip_event=True,
            )
        if added or removed:
            result = store.mutate_and_ircft(ws, [rel], source=source, added=added, removed=removed, personal=True, category_name=category_name)
        else:
            result = {"affected_files": [rel], "matrix": None}
        return {
            "center": ws,
            "group": pack.person_name,
            "category": category_name,
            "term": term,
            "terms": terms,
            "matrix": result.get("matrix") or {**build_matrix(), "center": ws},
            "affected_files": result.get("affected_files") or [],
        }


def refresh(
    center: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Bank fetch for every periodic-consent person (append-only). Manual-upload people are skipped."""
    from app.matrix import refresh_all

    with _center_scope(center) as ws:
        result = refresh_all(date_from=date_from, date_to=date_to)

    mut = store.mutate_and_publish(ws, [], source="central")
    matrix_payload = mut.get("matrix") or result.get("matrix") or {}
    if isinstance(matrix_payload, dict):
        matrix_payload = {**matrix_payload, "center": ws}
    # Keep per-person fetch stats (transaction_count, skipped, …) from refresh_all.
    return {
        **result,
        "center": ws,
        "matrix": matrix_payload,
        "affected_files": mut.get("affected_files") or [],
        "results": list(result.get("results") or []),
        "warnings": list(result.get("warnings") or []),
    }


def refresh_person(
    center: str,
    person_name: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    new_year: bool = False,
) -> dict[str, Any]:
    """Refresh one person; optional new-year overwrite applies only to that person."""
    from app.matrix import refresh_person as matrix_refresh_person
    from app.people import get_person

    with _center_scope(center) as ws:
        pack = get_person(person_name)
        result = matrix_refresh_person(
            person_name,
            date_from=date_from,
            date_to=date_to,
            new_year=new_year,
        )
        from app import consent_flow

        # Person-only fetch completed (or re-skipped); drop the post-callback prompt.
        consent_flow.clear_ready(center=ws, person_name=pack.person_name)

    mut = store.mutate_and_publish(ws, [], source="central")
    matrix_payload = mut.get("matrix") or result.get("matrix") or {}
    if isinstance(matrix_payload, dict):
        matrix_payload = {**matrix_payload, "center": ws}
    return {
        **result,
        "center": ws,
        "matrix": matrix_payload,
        "affected_files": mut.get("affected_files") or [],
        "results": list(result.get("results") or []),
        "warnings": list(result.get("warnings") or []),
    }



def _set_profile_app_id(profile: dict[str, Any], app_id: str) -> dict[str, Any]:
    connections = profile.get("connections")
    if not isinstance(connections, list):
        connections = []
    aspsp = ""
    country = ""
    conn: dict[str, Any] | None = None
    for item in connections:
        if not isinstance(item, dict):
            continue
        item_aspsp = str(item.get("aspsp") or "").strip()
        item_country = str(item.get("country") or "").strip()
        if item_aspsp and item_country:
            aspsp, country = item_aspsp, item_country
            conn = item
            break
    if not aspsp:
        aspsp = str(profile.get("aspsp") or "ING")
    if not country:
        country = str(profile.get("country") or "NL")
    if conn is None:
        conn = {"aspsp": aspsp, "country": country, "accounts": []}
        connections.append(conn)
    conn["app_id"] = app_id
    profile["connections"] = connections
    for key in ("app_id", "key_file", "redirect_url", "aspsp", "country", "account_name"):
        profile.pop(key, None)
    return profile


_PERSON_NAME_MAX = 40


def _valid_person_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or ".." in cleaned or "/" in cleaned or "\\" in cleaned:
        raise ValueError(f"Invalid person name: {name!r}")
    if not all(c.isalnum() or c in "_-" for c in cleaned):
        raise ValueError(
            f"Person name must be alphanumeric/underscore/hyphen: {name!r}"
        )
    if len(cleaned) > _PERSON_NAME_MAX:
        raise ValueError(f"Person name too long (max {_PERSON_NAME_MAX}): {name!r}")
    return cleaned


def create_person(
    center: str,
    *,
    person: str,
    title: str = "",
    account_name: str = "",
    mode: str = "periodic-consent",
    country: str = "NL",
    aspsp: str = "ING",
    initial_balance: str | None = None,
    account_number: str | None = None,
    mobile_phone: str | None = None,
) -> dict[str, Any]:
    """Create a person in SQL Server (agrolav-sql)."""
    person_name = _valid_person_name(person)
    mode_s = (mode or "periodic-consent").strip().lower()
    if mode_s not in {"periodic-consent", "manual-upload"}:
        raise ValueError("mode must be 'periodic-consent' or 'manual-upload'")
    holder = (account_name or "").strip()
    display_name = (title or "").strip()
    if mode_s == "manual-upload" and not display_name:
        raise ValueError("Name is required")
    if mode_s == "manual-upload" and not holder:
        raise ValueError("account holder name is required")
    account_no = (account_number or "").strip()
    country_s = (country or "NL").strip().upper()
    if len(country_s) != 2:
        raise ValueError(f"country must be ISO alpha-2: {country!r}")
    aspsp_s = (aspsp or "ING").strip()
    if not aspsp_s:
        raise ValueError("aspsp is required")
    from app.user_store import normalize_mobile_phone

    mobile = normalize_mobile_phone(mobile_phone)

    with _center_scope(center) as ws:
        from app import user_store

        if user_store.database_url():
            from app.sql_catalog import country_for_center, people_in_center

            country_name = country_for_center(ws)
            if not country_name:
                raise ValueError(f"Unknown center: {ws}")
            if person_name.lower() in {name.lower() for name in people_in_center(ws)}:
                raise ValueError(f"Person already exists: {person_name}")
            if mode_s == "periodic-consent":
                login = user_store.upsert_personal_login(
                    center=ws,
                    person=person_name,
                    country=country_name,
                    title="",
                    mobile_phone=mobile,
                )
                user_store.set_user_format(username=person_name, format=aspsp_s)
                return {
                    "ok": True,
                    "center": ws,
                    "person": person_name,
                    "mode": "periodic-consent",
                    "login": login,
                    "enable_banking_url": "https://enablebanking.com/cp/applications",
                }
            if mode_s == "manual-upload":
                created = user_store.create_manual_person(
                    center=ws,
                    person=person_name,
                    title=display_name,
                    country=country_name,
                    account_name=holder,
                    account_number=account_no,
                    initial_balance=initial_balance or "0",
                    mobile_phone=mobile,
                )
                store.announce_mutation(ws, [f"{person_name}/"], source="central")
                return {
                    "ok": True,
                    "center": ws,
                    "person": person_name,
                    "mode": "manual-upload",
                    "account_name": created.get("account_name"),
                    "account_number": created.get("account_number"),
                    "initial_balance": created.get("initial_balance"),
                    "login": created.get("login"),
                }

        raise RuntimeError(
            "SQL Server (agrolav-sql) is required — person creation is only supported via SQL."
        )


def upload_person_pem(
    center: str,
    person_name: str,
    *,
    filename: str,
    content: bytes,
) -> dict[str, Any]:
    """Store app_id + PEM in SQL (not as a file)."""
    from pathlib import Path

    from app import enable_sql
    from app.people import get_person
    from app.settings import refresh_people

    person = _valid_person_name(person_name)
    name = Path(filename).name
    if not name.lower().endswith(".pem"):
        raise ValueError("PEM upload must be a .pem file")
    stem = Path(name).stem.strip()
    if not stem:
        raise ValueError("PEM filename stem (Application ID) is empty")
    if not content or b"PRIVATE KEY" not in content:
        raise ValueError("File does not look like an RSA private key PEM")
    try:
        pem_text = content.decode("utf-8")
    except UnicodeDecodeError:
        pem_text = content.decode("ascii")

    with _center_scope(center) as ws:
        from app.core.single_client import _db_aspsp_default, _db_country_iso

        pack = get_person(person)
        stored = enable_sql.upsert_person_pem(person, app_id=stem, pem=pem_text)
        profile = {
            "person": person,
            "connections": [
                {
                    "app_id": stem,
                    "aspsp": _db_aspsp_default(),
                    "country": _db_country_iso(),
                    "accounts": [],
                }
            ],
        }
        refresh_people()

    return {
        "ok": True,
        "center": ws,
        "person": person,
        "app_id": stem,
        "connection_id": stored["connection_id"],
        "stored": "database",
        "profile": profile,
    }


def bootstrap_person_fetch(
    center: str,
    person_name: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """First fetch after PEM install (defaults: 1 Jan current year … today)."""
    from datetime import date

    today = date.today()
    start = date_from or f"{today.year}-01-01"
    end = date_to or today.isoformat()
    return refresh_person(
        center,
        person_name,
        date_from=start,
        date_to=end,
        new_year=True,
    )
