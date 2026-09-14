"""Sunday–Saturday meal marks packed into dbo.maaltijden_data.code."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.db import connect

MEALS = ("O", "L", "A", "P")
MARKS = ("x", "v", "L")
BITS_PER_USER = 5
USER_MASK = 0b11111
MAX_USERS = 12  # 5 × 12 = 60 bits, inside signed BIGINT
DAGEN = (
    "Zondag",
    "Maandag",
    "Dinsdag",
    "Woensdag",
    "Donderdag",
    "Vrijdag",
    "Zaterdag",
)
MAANDEN = (
    "",
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
)


def sunday_of(day: date) -> date:
    return day - timedelta(days=(day.weekday() + 1) % 7)


def week_number(sunday: date) -> int:
    jan1 = date(sunday.year, 1, 1)
    first = sunday_of(jan1)
    return ((sunday - first).days // 7) + 1


def week_label(sunday: date) -> str:
    return f"{sunday.day} {MAANDEN[sunday.month]}"


def sundays_from_present() -> list[date]:
    """This week's Sunday through the last Sunday of the current calendar year."""
    start = sunday_of(date.today())
    end_year = date.today().year
    out: list[date] = []
    cursor = start
    while cursor.year <= end_year:
        out.append(cursor)
        cursor += timedelta(days=7)
        if cursor.year > end_year:
            break
    return out


def day_id(day: date) -> int:
    """Map a calendar date to maaltijden_data.id in 1..365.

    Leap-year 29 februari shares id 59 with 28 februari; days after that
    shift back by one so 31 december is always 365.
    """
    yday = day.timetuple().tm_yday
    leap = day.year % 4 == 0 and (day.year % 100 != 0 or day.year % 400 == 0)
    if leap and (day.month > 2 or (day.month == 2 and day.day == 29)):
        yday -= 1
    return max(1, min(int(yday), 365))


def _as_uint(code: Any) -> int:
    n = int(code or 0)
    if n < 0:
        n &= (1 << 64) - 1
    return n


def marks_from_bits(bits: int) -> dict[str, str]:
    o = "v" if bits & 1 else "x"
    lunch = "v" if bits & 2 else "x"
    p = "v" if bits & 8 else "x"
    if bits & 16:
        a = "L"
    else:
        a = "v" if bits & 4 else "x"
    return {"O": o, "L": lunch, "A": a, "P": p}


def bits_from_marks(marks: dict[str, str]) -> int:
    bits = 0
    if marks.get("O") == "v":
        bits |= 1
    if marks.get("L") == "v":
        bits |= 2
    a = marks.get("A") or "x"
    if a == "v":
        bits |= 4
    elif a == "L":
        bits |= 16
    if marks.get("P") == "v":
        bits |= 8
    return bits


def unpack_users(code: int, people: list[dict[str, Any]]) -> dict[str, str]:
    """Return mark keys ``{user_id}:{meal}`` for one day.

    Bit groups follow list order (row 0 = bits 0–4), not the raw ``id``
    values, so a dense ``1..N`` numbering is not required to read.
    """
    n = _as_uint(code)
    out: dict[str, str] = {}
    for slot, person in enumerate(people):
        packed = (n >> (BITS_PER_USER * slot)) & USER_MASK
        uid = int(person["person_id"])
        for meal, letter in marks_from_bits(packed).items():
            if letter != "x":
                out[f"{uid}:{meal}"] = letter
    return out


def patch_code(code: int, slot: int, meal: str, mark: str) -> int:
    shift = BITS_PER_USER * int(slot)
    n = _as_uint(code)
    packed = (n >> shift) & USER_MASK
    marks = marks_from_bits(packed)
    marks[meal] = mark
    n = (n & ~(USER_MASK << shift)) | (bits_from_marks(marks) << shift)
    return n


def _ensure_data(cursor: Any, conn: Any) -> None:
    cursor.execute("SELECT OBJECT_ID(N'dbo.maaltijden_data', N'U')")
    row = cursor.fetchone()
    if row is None or row[0] is None:
        cursor.execute(
            """
            CREATE TABLE dbo.maaltijden_data (
                id INT PRIMARY KEY,
                code BIGINT NOT NULL
            )
            """
        )
    cursor.execute(
        """
        INSERT INTO dbo.maaltijden_data (id, code)
        SELECT n, CAST(0 AS BIGINT)
        FROM (
            SELECT TOP (365)
                ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS n
            FROM sys.all_objects
        ) AS x
        WHERE NOT EXISTS (
            SELECT 1 FROM dbo.maaltijden_data d WHERE d.id = x.n
        )
        """
    )
    conn.commit()


def _empty_extra() -> list[dict[str, int]]:
    return [{"O": 0, "L": 0, "A_v": 0, "A_L": 0, "P": 0} for _ in range(7)]


def _ensure_extra(cursor: Any, conn: Any, present: date) -> None:
    cursor.execute("SELECT OBJECT_ID(N'dbo.maaltijden_extra', N'U')")
    row = cursor.fetchone()
    if row is None or row[0] is None:
        cursor.execute(
            """
            CREATE TABLE dbo.maaltijden_extra (
                id INT IDENTITY(1,1) PRIMARY KEY,
                ochtend INT NOT NULL,
                middag INT NOT NULL,
                avond INT NOT NULL,
                laat INT NOT NULL,
                pakket INT NOT NULL
            )
            """
        )
    cursor.execute("SELECT COUNT(*) FROM dbo.maaltijden_extra")
    n = int(cursor.fetchone()[0] or 0)
    if n < 7:
        for _ in range(7 - n):
            cursor.execute(
                """
                INSERT INTO dbo.maaltijden_extra
                    (ochtend, middag, avond, laat, pakket)
                VALUES (0, 0, 0, 0, 0)
                """
            )
    cursor.execute("SELECT OBJECT_ID(N'dbo.maaltijden_extra_week', N'U')")
    row = cursor.fetchone()
    if row is None or row[0] is None:
        cursor.execute(
            "CREATE TABLE dbo.maaltijden_extra_week (week_start DATE NOT NULL)"
        )
    cursor.execute("SELECT TOP (1) week_start FROM dbo.maaltijden_extra_week")
    stored = cursor.fetchone()
    week_start = None if stored is None else stored[0]
    if hasattr(week_start, "date"):
        week_start = week_start.date()
    if week_start is None or week_start < present:
        cursor.execute(
            """
            UPDATE dbo.maaltijden_extra
            SET ochtend = 0, middag = 0, avond = 0, laat = 0, pakket = 0
            """
        )
        cursor.execute("DELETE FROM dbo.maaltijden_extra_week")
        cursor.execute(
            "INSERT INTO dbo.maaltijden_extra_week (week_start) VALUES (?)",
            (present.isoformat(),),
        )
    conn.commit()


def _load_extra(cursor: Any) -> list[dict[str, int]]:
    extra = _empty_extra()
    cursor.execute(
        """
        SELECT TOP (7) ochtend, middag, avond, laat, pakket
        FROM dbo.maaltijden_extra
        ORDER BY id
        """
    )
    for i, (ochtend, middag, avond, laat, pakket) in enumerate(cursor.fetchall()):
        extra[i] = {
            "O": int(ochtend or 0),
            "L": int(middag or 0),
            "A_v": int(avond or 0),
            "A_L": int(laat or 0),
            "P": int(pakket or 0),
        }
    return extra


def _load_users(cursor: Any) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT u.id, u.user_login, p.title
        FROM dbo.maaltijden_users u
        LEFT JOIN dbo.person p
            ON p.username COLLATE Latin1_General_CI_AI
             = u.user_login COLLATE Latin1_General_CI_AI
        ORDER BY u.id
        """
    )
    people: list[dict[str, Any]] = []
    for uid, login, title in cursor.fetchall():
        username = str(login or "").strip()
        name = str(title or "").strip() or username
        people.append(
            {
                "person_id": int(uid),
                "username": username,
                "title": name,
            }
        )
    if not people:
        raise RuntimeError("dbo.maaltijden_users is empty")
    if len(people) > MAX_USERS:
        raise RuntimeError(f"dbo.maaltijden_users has more than {MAX_USERS} rows")
    return people


def _days(sunday: date) -> list[dict[str, Any]]:
    days = []
    for i in range(7):
        d = sunday + timedelta(days=i)
        days.append(
            {
                "weekday": i,
                "date": d.isoformat(),
                "day": d.day,
                "month": d.month,
                "month_name": MAANDEN[d.month],
                "dag": DAGEN[i],
                "day_id": day_id(d),
            }
        )
    return days


def _month_spans(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for day in days:
        month = int(day["month"])
        if spans and spans[-1]["month"] == month:
            spans[-1]["span"] += 1
        else:
            spans.append(
                {
                    "month": month,
                    "name": str(day["month_name"]),
                    "span": 1,
                }
            )
    return spans


def week_payload(sunday: date, *, me_username: str, access: str) -> dict[str, Any]:
    present = sunday_of(date.today())
    sunday = sunday_of(sunday)
    available = sundays_from_present()
    if sunday < present or sunday not in available:
        sunday = present
    days = _days(sunday)
    day_ids = [int(d["day_id"]) for d in days]
    try:
        with connect() as conn:
            cur = conn.cursor()
            _ensure_data(cur, conn)
            _ensure_extra(cur, conn, present)
            extra = _load_extra(cur)
            people = _load_users(cur)
            placeholders = ",".join("?" for _ in day_ids)
            cur.execute(
                f"SELECT id, code FROM dbo.maaltijden_data WHERE id IN ({placeholders})",
                tuple(day_ids),
            )
            codes = {int(row[0]): _as_uint(row[1]) for row in cur.fetchall()}
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    if sunday != present:
        extra = _empty_extra()
    marks: dict[str, str] = {}
    for d in days:
        packed = unpack_users(codes.get(int(d["day_id"]), 0), people)
        weekday = int(d["weekday"])
        for key, letter in packed.items():
            uid_s, meal = key.split(":", 1)
            marks[f"{uid_s}:{weekday}:{meal}"] = letter
    me = next(
        (p for p in people if p["username"].lower() == me_username.strip().lower()),
        None,
    )
    can_edit_all = False
    weeks = [
        {
            "sunday": start.isoformat(),
            "week": week_number(start),
            "label": week_label(start),
        }
        for start in sundays_from_present()
    ]
    return {
        "sunday": sunday.isoformat(),
        "week": week_number(sunday),
        "year": sunday.year,
        "days": days,
        "months": _month_spans(days),
        "meals": list(MEALS),
        "dagen": list(DAGEN),
        "people": people,
        "marks": marks,
        "extra": extra,
        "me": {
            "person_id": None if me is None else me["person_id"],
            "username": me_username,
            "access": access,
            "can_edit_all": can_edit_all,
        },
        "weeks": weeks,
    }


def set_mark(
    *,
    sunday: date,
    weekday: int,
    meal: str,
    mark: str,
    person_id: int,
    editor: dict[str, Any],
) -> dict[str, Any]:
    sunday = sunday_of(sunday)
    if sunday < sunday_of(date.today()):
        raise ValueError("verleden")
    meal = str(meal or "").strip().upper()[:1]
    mark = str(mark or "x").strip()[:1]
    if weekday < 0 or weekday > 6:
        raise ValueError("weekday")
    if meal not in MEALS:
        raise ValueError("meal")
    if mark == "L":
        if meal != "A":
            raise ValueError("mark")
    elif mark not in ("x", "v"):
        raise ValueError("mark")
    day = sunday + timedelta(days=int(weekday))
    slot = day_id(day)
    with connect() as conn:
        cur = conn.cursor()
        people = _load_users(cur)
        target = next((p for p in people if p["person_id"] == int(person_id)), None)
        if target is None:
            raise ValueError("person")
        bit_slot = next(
            i for i, p in enumerate(people) if p["person_id"] == int(person_id)
        )
        me_name = str(editor.get("person") or editor.get("username") or "").strip().lower()
        if target["username"].lower() != me_name:
            raise PermissionError("niet jouw rij")
        _ensure_data(cur, conn)
        cur.execute("SELECT code FROM dbo.maaltijden_data WHERE id = ?", (slot,))
        row = cur.fetchone()
        current = _as_uint(row[0]) if row is not None else 0
        updated = patch_code(current, bit_slot, meal, mark)
        if row is None:
            cur.execute(
                "INSERT INTO dbo.maaltijden_data (id, code) VALUES (?, ?)",
                (slot, updated),
            )
        else:
            cur.execute(
                "UPDATE dbo.maaltijden_data SET code = ? WHERE id = ?",
                (updated, slot),
            )
        conn.commit()
    return {
        "ok": True,
        "person_id": int(person_id),
        "sunday": sunday.isoformat(),
        "weekday": int(weekday),
        "meal": meal,
        "mark": mark,
        "day_id": slot,
        "code": updated,
    }
