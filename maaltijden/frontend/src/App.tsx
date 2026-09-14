import { FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import {
  getMe,
  getWeek,
  login,
  logout,
  markKey,
  saveMark,
  type PersonRow,
  type Session,
  type WeekData,
  type WeekOption,
} from "./api";

type View = "matrix" | "person";

function nextMark(current: string, meal: string): string {
  if (meal === "A") {
    const order = ["x", "v", "L"] as const;
    const i = order.indexOf(current as (typeof order)[number]);
    return order[(i < 0 ? 0 : i + 1) % order.length];
  }
  return current === "v" ? "x" : "v";
}

function cellMark(data: WeekData, personId: number, weekday: number, meal: string): string {
  return data.marks[markKey(personId, weekday, meal)] || "x";
}

function extraValue(data: WeekData, weekday: number, meal: string): string {
  const extra = data.extra?.[weekday];
  if (!extra) return meal === "A" ? "0/0" : "0";
  if (meal === "A") return `${extra.A_v}/${extra.A_L}`;
  if (meal === "O") return String(extra.O);
  if (meal === "L") return String(extra.L);
  return String(extra.P);
}

function columnTotal(data: WeekData, weekday: number, meal: string): string {
  let v = 0;
  let later = 0;
  for (const person of data.people) {
    const mark = cellMark(data, person.person_id, weekday, meal);
    if (mark === "v") v += 1;
    else if (mark === "L") later += 1;
  }
  const extra = data.extra?.[weekday];
  if (extra) {
    if (meal === "A") {
      v += extra.A_v;
      later += extra.A_L;
    } else if (meal === "O") v += extra.O;
    else if (meal === "L") v += extra.L;
    else v += extra.P;
  }
  if (meal === "A") return `${v}/${later}`;
  return String(v);
}

function canEdit(data: WeekData, person: PersonRow): boolean {
  if (data.me.can_edit_all) return true;
  return data.me.person_id != null && data.me.person_id === person.person_id;
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

function MarkCell({
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
      className={`mark mark-${value} ${disabled ? "is-locked" : ""}`}
      disabled={disabled}
      onClick={onCycle}
    >
      {value}
    </button>
  );
}

function MatrixView({
  data,
  onCycle,
}: {
  data: WeekData;
  onCycle: (person: PersonRow, weekday: number, meal: string) => void;
}) {
  return (
    <div className="sheet-wrap">
      <table className="meal-table">
        <thead>
          <tr>
            <th className="name-col" rowSpan={3} />
            {data.months.map((m) => (
              <th key={`${m.month}-${m.name}`} className="month" colSpan={m.span * data.meals.length}>
                {m.name}
              </th>
            ))}
          </tr>
          <tr>
            {data.days.map((d) => (
              <th key={d.date} className="dom" colSpan={data.meals.length}>
                {d.day}
              </th>
            ))}
          </tr>
          <tr>
            {data.days.map((d) =>
              data.meals.map((meal) => (
                <th key={`${d.date}-${meal}`} className={meal === "A" ? "meal meal-a" : "meal"}>
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
              {data.days.map((d) =>
                data.meals.map((meal) => (
                  <td key={`${p.person_id}-${d.weekday}-${meal}`} className={meal === "A" ? "meal-a" : undefined}>
                    <MarkCell
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
            <th className="name-col">extra</th>
            {data.days.map((d) =>
              data.meals.map((meal) => (
                <td key={`extra-${d.weekday}-${meal}`} className={meal === "A" ? "total-a" : undefined}>
                  {extraValue(data, d.weekday, meal)}
                </td>
              ))
            )}
          </tr>
          <tr className="totals">
            <th className="name-col">totalen</th>
            {data.days.map((d) =>
              data.meals.map((meal) => (
                <td key={`total-${d.weekday}-${meal}`} className={meal === "A" ? "total-a" : undefined}>
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

function PersonView({
  data,
  onCycle,
}: {
  data: WeekData;
  onCycle: (person: PersonRow, weekday: number, meal: string) => void;
}) {
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
                <span className="dag">{d.dag}</span>
                <span className="dom-inline">
                  {d.day} {d.month_name}
                </span>
              </th>
              {data.meals.map((meal) => (
                <td key={meal}>
                  <MarkCell
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
  const [view, setView] = useState<View>("matrix");
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
    const mark = nextMark(current, meal);
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

  if (!authChecked) return <p className="hint">Laden…</p>;
  if (!session) return <LoginScreen onSuccess={setSession} />;

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
                  className={view === "matrix" ? "is-selected" : undefined}
                  onClick={() => {
                    close();
                    setView("matrix");
                  }}
                >
                  Matrix
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
                  Persoon
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
            });
          }}
        >
          Uitloggen
        </button>
      </div>
      <hr className="rule" />
      {error ? <p className="login-error">{error}</p> : null}
      {data && view === "matrix" ? <MatrixView data={data} onCycle={cycle} /> : null}
      {data && view === "person" ? <PersonView data={data} onCycle={cycle} /> : null}
    </div>
  );
}
