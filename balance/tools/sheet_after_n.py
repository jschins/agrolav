"""Read-only diagnostic: balance sheet as of a given booking date (or after the
first N rows of dbo.transaction_beheer).

The sheet's only transaction-driven figures are Verlies (2100; sum of amounts
in categories 3000-4999 plus the journal overlay) and the balancing Eigen
vermogen (2000). Everything else comes from opening balances, live bank
accounts and the journal tables.

Usage:
    python tools/sheet_after_n.py [N [N2 ...]] [--date YYYY-MM-DD]
                                  [--year Y [--country C]] [--no-overlay] [--live-banks]

With N:          sheet after the first N inserted rows.
With --date D:   sheet as of end of day D (rows with booked_on <= D); bank
                 categories 1051/1053-1056 are shown as-of D (current balance
                 minus later movements, unless --live-banks).
With neither:    full prefix; prints a parity check against the live sheet
                 (must reproduce it exactly).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import balance  # noqa: E402
from app.db import connect  # noqa: E402

NON_RESULT_CATS = {
    1000, 1005, 1010, 1015, 1051, 1052, 1053, 1054, 1055, 1056,
    1110, 1111, 2000, 2050, 2055, 2100, 2500,
}


def _rows(country_id: int, year: int) -> list[dict[str, Any]]:
    table = balance._transaction_table(country_id)
    if table is None:
        raise SystemExit(f"no transaction table for country {country_id}")
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT id, booked_on, category_id, account_id, amount, description "
            f"FROM {table} WHERE year = ? ORDER BY booked_on, id",
            year,
        )
        return [
            {
                "id": int(r[0]),
                "booked_on": str(r[1]),
                "category_id": int(r[2]),
                "account_id": int(r[3]) if r[3] is not None else None,
                "amount": Decimal(str(r[4])),
                "description": str(r[5] or ""),
            }
            for r in cur.fetchall()
        ]


def _account_balances_asof(country_id: int, rows: list[dict[str, Any]], cutoff: Any) -> dict[int, Decimal]:
    """account_id → balance as of ``cutoff`` (lives as-is when not date-framed)."""
    if cutoff is None:
        return balance._account_balances(country_id)
    current = balance._account_balances(country_id)
    later: dict[int, Decimal] = {}
    for r in rows:
        if r["account_id"] is None or not (cutoff_lt(r["booked_on"], cutoff)):
            continue
        later[r["account_id"]] = later.get(r["account_id"], Decimal("0")) + r["amount"]
    return {aid: (cur - later.get(aid, Decimal("0"))) for aid, cur in current.items()}


def cutoff_lt(booked_on: str, cutoff: Any) -> bool:
    if isinstance(cutoff, date):
        return booked_on[:10] > cutoff.isoformat()
    return False


def _result_from_rows(rows: list[dict[str, Any]]) -> Decimal:
    return sum(
        (r["amount"] for r in rows if 3000 <= r["category_id"] <= 4999),
        Decimal("0"),
    )


def _sheet(country_id: int, year: int, result_amount: Decimal,
           acct: dict[int, Decimal]) -> dict[str, Any]:
    opening = balance._opening_balances(country_id, year)
    journal = balance._journal_balances(country_id, year)
    journal_effect = balance._journal_effect(country_id, year)
    labels = balance._category_labels(country_id)
    category_map = balance._category_map(country_id)
    balance_id = balance._balance_id(country_id)
    result_id = balance._verlies_id(country_id)

    activa: list[dict[str, Any]] = []
    passiva: list[dict[str, Any]] = []

    for cat_id in sorted(category_map):
        if cat_id in (balance_id, result_id):
            continue
        side, account_id = category_map[cat_id]
        label = labels.get(cat_id, f"cat_{cat_id}")
        if account_id is not None:
            amount = acct.get(account_id, Decimal("0"))
            source = f"account:{account_id}"
        else:
            amount = opening.get(cat_id, Decimal("0"))
            source = "opening"
        ja = journal.get(cat_id)
        if ja is not None:
            amount += ja
            source += "+journal"
        eff = journal_effect.get(cat_id)
        if eff:
            amount += eff
            if "+journal" not in source:
                source += "+journal"
        row = {"category_id": cat_id, "label": label, "amount": amount, "source": source}
        (activa if side == "activa" else passiva).append(row)

    total_activa = sum((r["amount"] for r in activa), Decimal("0"))
    passiva.append({"category_id": result_id, "label": labels.get(result_id, "Verlies"),
                    "amount": result_amount,
                    "source": "rows <= cutoff"})
    total_others = sum((r["amount"] for r in passiva), Decimal("0"))
    passiva.append({"category_id": balance_id, "label": labels.get(balance_id, "Eigen vermogen"),
                    "amount": total_activa - total_others, "source": "computed"})
    total_passiva = sum((r["amount"] for r in passiva), Decimal("0"))
    return {"year": year, "country_id": country_id, "activa": activa,
            "passiva": passiva, "total_activa": total_activa,
            "total_passiva": total_passiva, "balanced": total_activa == total_passiva}


def _fmt(d: Decimal) -> str:
    return f"{d:,.2f}"


def print_sheet(s: dict[str, Any]) -> None:
    print(f"  Activa  ({_fmt(s['total_activa'])})")
    for r in s["activa"]:
        print(f"    {r['category_id']:>5} {r['label']:<26} {_fmt(r['amount']):>15}  ({r['source']})")
    print(f"  Passiva ({_fmt(s['total_passiva'])})")
    for r in s["passiva"]:
        print(f"    {r['category_id']:>5} {r['label']:<26} {_fmt(r['amount']):>15}  ({r['source']})")
    print(f"  balanced: {s['balanced']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("n", nargs="*", type=int, help="prefix lengths (default: full)")
    ap.add_argument("--date", dest="d", help="as-of booking date YYYY-MM-DD")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--country", type=int, default=4)
    ap.add_argument("--no-overlay", action="store_true",
                    help="exclude the journal overlay from Verlies")
    ap.add_argument("--live-banks", action="store_true",
                    help="keep live (current) bank balances instead of as-of date")
    args = ap.parse_args()

    country_id, year = args.country, args.year
    rows = _rows(country_id, year)
    overlay = Decimal("0") if args.no_overlay else balance._result_overlay(country_id, year)
    print(f"transaction_beheer: {len(rows)} rows (year {year}, country {country_id}); "
          f"journal overlay {_fmt(overlay)}")

    full_n = len(rows)
    cutoff = None
    if args.d:
        cutoff = date.fromisoformat(args.d)
        prefix = [r for r in rows if cutoff_lt(r["booked_on"], cutoff) == False and r["booked_on"][:10] <= args.d]
        acct = balance._account_balances(country_id) if args.live_banks else _account_balances_asof(
            country_id, rows, cutoff)
        ns = []
    else:
        prefix = rows
        acct = balance._account_balances(country_id)

    report_ns: list[int] = []

    if cutoff is not None:
        print(f"\n==== Sheet as of {cutoff} (rows with booked_on <= {cutoff}) ====")
        base = _result_from_rows(prefix)
        result = base + overlay
        print(f"  Verlies 2100 = {_fmt(result)} "
              f"(prefix 3000-4999 sum {_fmt(base)} + overlay {_fmt(overlay)}; "
              f"{len(prefix)} of {full_n} rows)")
        print_sheet(_sheet(country_id, year, result, acct))
        print(f"\n  Per-booked-day cumulative Verlies 2100 (rows <= day), overlay included={not args.no_overlay}:")
        seen: dict[str, Decimal] = {}
        run = Decimal("0")
        for r in rows:
            run += r["amount"] if 3000 <= r["category_id"] <= 4999 else Decimal("0")
            seen[r["booked_on"][:10]] = run
        for day, tot in seen.items():
            print(f"    {day}  cum 3000-4999 = {_fmt(tot)}  -> sheet Verlies = {_fmt(tot + overlay)}")
    else:
        ns = args.n or [full_n]
        for n in ns:
            if not (0 <= n <= full_n):
                print(f"  N={n} out of range (0..{full_n}), skipped")
                continue
            report_ns.append(n)
            prefix = rows[:n]
            base = _result_from_rows(prefix)
            result = base + overlay
            print(f"\n==== N = {n} of {full_n} ====")
            print(f"  Verlies 2100 = {_fmt(result)} "
                  f"(first-N 3000-4999 sum {_fmt(base)} + overlay {_fmt(overlay)})")
            print_sheet(_sheet(country_id, year, result, acct))
            if n == full_n:
                live = balance.balance_sheet(country_id, year)
                live_v = Decimal(str(next(r["amount"] for r in live["passiva"] if r["category_id"] == 2100)))
                live_e = Decimal(str(next(r["amount"] for r in live["passiva"] if r["category_id"] == 2000)))
                diag_v = Decimal(str(next(r["amount"] for r in _sheet(country_id, year, result, acct)["passiva"] if r["category_id"] == 2100)))
                diag_e = Decimal(str(next(r["amount"] for r in _sheet(country_id, year, result, acct)["passiva"] if r["category_id"] == 2000)))
                print(f"  [PARITY] live Verlies {_fmt(live_v)} == diag {_fmt(diag_v)}; "
                      f"live Eigen {_fmt(live_e)} == diag {_fmt(diag_e)}; full-match="
                      f"{live_v == diag_v and live_e == diag_e}")

    if cutoff is None:
        top = max(report_ns) if report_ns else 0
        if top > 0 and not (len(report_ns) == 1 and report_ns[0] == full_n):
            print("\nPer-transaction effect on Verlies (res) — row amount if the category is "
                  "3000-4999, else 0: ('*' marks a non-result category)")
            for r in rows[:top]:
                res = r["amount"] if 3000 <= r["category_id"] <= 4999 else Decimal("0")
                mark = "*" if r["category_id"] in NON_RESULT_CATS else " "
                print(f"  {r['id']:>6} {r['booked_on'][:10]} {r['category_id']:>5} {mark} "
                      f"res={_fmt(res):>13} amt={_fmt(r['amount']):>13}  {r['description'][:48]}")


if __name__ == "__main__":
    main()