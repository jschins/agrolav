import { FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import {
  getMe,
  getWeek,
  login,
  logout,
  markKey,
  saveExtra,
  saveMark,
  type ExtraDay,
  type MonthSpan,
  type PersonRow,
  type Session,
  type WeekData,
  type WeekDay,
  type WeekOption,
} from "./api";

type View = "day" | "week" | "person";

const EMPTY_EXTRA: ExtraDay = { O: 0, M: 0, A: 0, L: 0, P: 0 };

const EXTRA_LABELS: Record<keyof ExtraDay, string> = {
  O: "Ochtend extra",
  M: "Middag extra",
  A: "Avond extra",
  L: "Laat extra",
  P: "Pakket extra",
};

function extraKey(meal: string): keyof ExtraDay | null {
  if (meal === "O" || meal === "M" || meal === "A" || meal === "L" || meal === "P") {
    return meal;
  }
  return null;
}

function nextMark(current: string): string {
  return current === "v" ? "x" : "v";
}

function cellMark(data: WeekData, personId: number, weekday: number, meal: string): string {
  return data.marks[markKey(personId, weekday, meal)] || "x";
}

function columnTotal(data: WeekData, weekday: number, meal: string): string {
  const key = extraKey(meal);
  let v = 0;
  for (const person of data.people) {
    if (cellMark(data, person.person_id, weekday, meal) === "v") v += 1;
  }
  const extra = extraDay(data, weekday);
  if (key) v += extra[key];
  return String(v);
}

function canEdit(data: WeekData, person: PersonRow): boolean {
  if (data.me.is_admin) return false;
  if (data.me.can_edit_all) return true;
  return data.me.person_id != null && data.me.person_id === person.person_id;
}

function extraDay(data: WeekData, weekday: number): ExtraDay {
  return data.extra?.[weekday] || { ...EMPTY_EXTRA };
}

function parseCount(raw: string): number {
  const n = parseInt(raw.replace(/\D/g, ""), 10);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.min(n, 999);
}

function extraValueFrom(extra: ExtraDay, meal: string): string {
  const key = extraKey(meal);
  return String(key ? extra[key] : 0);
}

function monthSpans(days: WeekDay[]): MonthSpan[] {
  const spans: MonthSpan[] = [];
  for (const day of days) {
    if (spans.length && spans[spans.length - 1].month === day.month) {
      spans[spans.length - 1].span += 1;
    } else {
      spans.push({ month: day.month, name: day.month_name, span: 1 });
    }
  }
  return spans;
}

function todayIso(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function daysForView(data: WeekData, view: View): WeekDay[] {
  if (view !== "day") return data.days;
  const today = todayIso();
  const exact = data.days.filter((d) => d.date === today);
  if (exact.length) return exact;
  const weekday = new Date().getDay();
  const same = data.days.filter((d) => d.weekday === weekday);
  return same.length ? same : data.days.slice(0, 1);
}

const DAG_KORT = ["zo", "ma", "di", "wo", "do", "vr", "za"] as const;

function dayShort(d: WeekDay): string {
  return `${DAG_KORT[d.weekday] ?? ""} ${d.day}`;
}

function ExtraInputs({
  extra,
  meal,
  disabled,
  onChange,
}: {
  extra: ExtraDay;
  meal: string;
  disabled: boolean;
  onChange: (patch: Partial<ExtraDay>) => void;
}) {
  const key = extraKey(meal);
  if (!key) return null;
  if (disabled) {
    return <>{extraValueFrom(extra, meal)}</>;
  }
  return (
    <input
      className="extra-input"
      type="text"
      inputMode="numeric"
      aria-label={EXTRA_LABELS[key]}
      value={extra[key]}
      onChange={(e) => onChange({ [key]: parseCount(e.target.value) })}
    />
  );
}

function DropMenu({
  label,
  children,
}: {
  label: string;
  children: (close: () => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(ev: Event) {
      if (!rootRef.current?.contains(ev.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="center-switcher" ref={rootRef}>
      <button
        type="button"
        className="center-switcher-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="center-switcher-chevron" aria-hidden>
          ▾
        </span>
        <span className="center-switcher-label">{label}</span>
      </button>
      {open ? (
        <ul className="center-switcher-menu" role="listbox">
          {children(() => setOpen(false))}
        </ul>
      ) : null}
    </div>
  );
}

function LoginScreen({ onSuccess }: { onSuccess: (s: Session) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function fail(err: Error) {
    const text = err.message || "";
    if (text.includes("401")) {
      setError("Ongeldige gebruikersnaam of wachtwoord");
    } else {
      setError(text);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    login(username.trim(), password)
      .then(onSuccess)
      .catch(fail)
      .finally(() => setBusy(false));
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <h1 className="login-title">Maaltijden</h1>
        <label className="login-label">
          Gebruikersnaam
          <input
            className="login-input"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={busy}
            required
          />
        </label>
        <label className="login-label">
          Wachtwoord
          <input
            className="login-input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={busy}
          />
        </label>
        {error ? <p className="login-error">{error}</p> : null}
        <button className="login-submit" type="submit" disabled={busy}>
          {busy ? "Bezig…" : "Aanmelden"}
        </button>
      </form>
    </div>
  );
}

function MatrixMarkCell({
  value,
  disabled,
  onCycle,
}: {
  value: string;
  disabled: boolean;
  onCycle: () => void;
}) {
  return (
    <button
      type="button"
      className={`mark-dot mark-${value} ${disabled ? "is-locked" : ""}`}
      disabled={disabled}
      aria-label={value}
      onClick={onCycle}
    />
  );
}

function MatrixView({
  data,
  days,
  onCycle,
  onExtra,
}: {
  data: WeekData;
  days: WeekDay[];
  onCycle: (person: PersonRow, weekday: number, meal: string) => void;
  onExtra: (weekday: number, patch: Partial<ExtraDay>) => void;
}) {
  const months = monthSpans(days);
  return (
    <div className="sheet-wrap">
      <table className="meal-table">
        <thead>
          <tr>
            <th className="name-col" rowSpan={3} />
            {months.map((m) => (
              <th key={`${m.month}-${m.name}`} className="month" colSpan={m.span * data.meals.length}>
                {m.name}
              </th>
            ))}
          </tr>
          <tr>
            {days.map((d) => (
              <th key={d.date} className="dom" colSpan={data.meals.length}>
                {d.day}
              </th>
            ))}
          </tr>
          <tr>
            {days.map((d) =>
              data.meals.map((meal) => (
                <th key={`${d.date}-${meal}`} className="meal">
                  {meal}
                </th>
              ))
            )}
          </tr>
        </thead>
        <tbody>
          {data.people.map((p) => (
            <tr key={p.person_id}>
              <th className="name-col">{p.title}</th>
              {days.map((d) =>
                data.meals.map((meal) => (
                  <td key={`${p.person_id}-${d.weekday}-${meal}`}>
                    <MatrixMarkCell
                      value={cellMark(data, p.person_id, d.weekday, meal)}
                      disabled={!canEdit(data, p)}
                      onCycle={() => onCycle(p, d.weekday, meal)}
                    />
                  </td>
                ))
              )}
            </tr>
          ))}
          <tr className="totals extra">
            <th className="name-col">ex</th>
            {days.map((d) =>
              data.meals.map((meal) => (
                <td key={`extra-${d.weekday}-${meal}`}>
                  <ExtraInputs
                    extra={extraDay(data, d.weekday)}
                    meal={meal}
                    disabled={!data.me.can_edit_extra}
                    onChange={(patch) => onExtra(d.weekday, patch)}
                  />
                </td>
              ))
            )}
          </tr>
          <tr className="totals">
            <th className="name-col">tot</th>
            {days.map((d) =>
              data.meals.map((meal) => (
                <td key={`total-${d.weekday}-${meal}`}>
                  {columnTotal(data, d.weekday, meal)}
                </td>
              ))
            )}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function ExtraPersonView({
  data,
  onExtra,
}: {
  data: WeekData;
  onExtra: (weekday: number, patch: Partial<ExtraDay>) => void;
}) {
  const locked = !data.me.can_edit_extra;
  return (
    <div className="sheet-wrap person-wrap">
      {locked ? <p className="hint">Extra alleen deze week.</p> : null}
      <table className="meal-table person-table">
        <thead>
          <tr>
            <th className="name-col">Dag</th>
            {data.meals.map((meal) => (
              <th key={meal} className="meal">
                {meal}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.days.map((d) => (
            <tr key={d.date}>
              <th className="name-col">
                {dayShort(d)}
              </th>
              {data.meals.map((meal) => (
                <td key={meal}>
                  <ExtraInputs
                    extra={extraDay(data, d.weekday)}
                    meal={meal}
                    disabled={locked}
                    onChange={(patch) => onExtra(d.weekday, patch)}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PersonView({
  data,
  onCycle,
  onExtra,
}: {
  data: WeekData;
  onCycle: (person: PersonRow, weekday: number, meal: string) => void;
  onExtra: (weekday: number, patch: Partial<ExtraDay>) => void;
}) {
  if (data.me.is_admin) {
    return <ExtraPersonView data={data} onExtra={onExtra} />;
  }
  const me = data.people.find((p) => p.person_id === data.me.person_id);
  if (!me) {
    return <p className="hint">Alleen beschikbaar bij persoonlijke aanmelding.</p>;
  }
  return (
    <div className="sheet-wrap person-wrap">
      <table className="meal-table person-table">
        <thead>
          <tr>
            <th className="name-col">Dag</th>
            {data.meals.map((meal) => (
              <th key={meal} className="meal">
                {meal}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.days.map((d) => (
            <tr key={d.date}>
              <th className="name-col">
                {dayShort(d)}
              </th>
              {data.meals.map((meal) => (
                <td key={meal}>
                  <MatrixMarkCell
                    value={cellMark(data, me.person_id, d.weekday, meal)}
                    disabled={!canEdit(data, me)}
                    onCycle={() => onCycle(me, d.weekday, meal)}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [data, setData] = useState<WeekData | null>(null);
  const [sunday, setSunday] = useState<string>("");
  const [view, setView] = useState<View>("day");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMe()
      .then((s) => setSession(s))
      .catch(() => setSession(null))
      .finally(() => setAuthChecked(true));
  }, []);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    setError(null);
    getWeek(sunday || undefined)
      .then((week) => {
        if (cancelled) return;
        setData(week);
        setSunday(week.sunday);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [session, sunday]);

  function cycle(person: PersonRow, weekday: number, meal: string) {
    if (!data || !canEdit(data, person)) return;
    const current = cellMark(data, person.person_id, weekday, meal);
    const mark = nextMark(current);
    const key = markKey(person.person_id, weekday, meal);
    setData({ ...data, marks: { ...data.marks, [key]: mark } });
    saveMark({
      sunday: data.sunday,
      weekday,
      meal,
      mark,
      person_id: person.person_id,
    }).catch((e: Error) => {
      setError(e.message);
      setData({ ...data, marks: { ...data.marks, [key]: current } });
    });
  }

  function changeExtra(weekday: number, patch: Partial<ExtraDay>) {
    if (!data || !data.me.can_edit_extra) return;
    const previous = extraDay(data, weekday);
    const next: ExtraDay = { ...previous, ...patch };
    const extra = Array.from({ length: 7 }, (_, i) => (i === weekday ? next : extraDay(data, i)));
    setData({ ...data, extra });
    saveExtra({
      sunday: data.sunday,
      weekday,
      ...next,
    }).catch((e: Error) => {
      setError(e.message);
      setData({
        ...data,
        extra: Array.from({ length: 7 }, (_, i) => (i === weekday ? previous : extraDay(data, i))),
      });
    });
  }

  if (!authChecked) return <p className="hint">Laden…</p>;
  if (!session) {
    return (
      <LoginScreen
        onSuccess={(s) => {
          setView("day");
          setSunday("");
          setSession(s);
        }}
      />
    );
  }

  const weekLabel =
    data?.weeks.find((w) => w.sunday === (sunday || data.sunday))?.label || "Week";
  const viewLabel = "Weergave";

  return (
    <div className="shell">
      <div className="bar">
        <DropMenu label={weekLabel}>
          {(close) =>
            (data?.weeks || []).map((w: WeekOption) => (
              <li key={w.sunday}>
                <button
                  type="button"
                  role="option"
                  aria-selected={w.sunday === sunday}
                  className={w.sunday === sunday ? "is-selected" : undefined}
                  onClick={() => {
                    close();
                    setSunday(w.sunday);
                  }}
                >
                  {w.label}
                </button>
              </li>
            ))
          }
        </DropMenu>
        <DropMenu label={viewLabel}>
          {(close) => (
            <>
              <li>
                <button
                  type="button"
                  className={view === "day" ? "is-selected" : undefined}
                  onClick={() => {
                    close();
                    setSunday("");
                    setView("day");
                  }}
                >
                  Dag
                </button>
              </li>
              <li>
                <button
                  type="button"
                  className={view === "week" ? "is-selected" : undefined}
                  onClick={() => {
                    close();
                    setView("week");
                  }}
                >
                  Week
                </button>
              </li>
              <li>
                <button
                  type="button"
                  className={view === "person" ? "is-selected" : undefined}
                  onClick={() => {
                    close();
                    setView("person");
                  }}
                >
                  Reserveren
                </button>
              </li>
            </>
          )}
        </DropMenu>
        <button
          type="button"
          className="center-switcher-trigger logout"
          onClick={() => {
            logout().finally(() => {
              setSession(null);
              setData(null);
              setView("day");
              setSunday("");
            });
          }}
        >
          Uitloggen
        </button>
      </div>
      <hr className="rule" />
      {error ? <p className="login-error">{error}</p> : null}
      {data && (view === "day" || view === "week") ? (
        <MatrixView
          data={data}
          days={daysForView(data, view)}
          onCycle={cycle}
          onExtra={changeExtra}
        />
      ) : null}
      {data && view === "person" ? (
        <PersonView data={data} onCycle={cycle} onExtra={changeExtra} />
      ) : null}
    </div>
  );
}
