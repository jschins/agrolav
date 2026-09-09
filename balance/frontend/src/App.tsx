import { useCallback, useEffect, useRef, useState } from "react";
import { getDates, getMeta, getSheet, getYears, rebuildSpaarMirror } from "./api";
import JournalEditor from "./JournalEditor";
import type { BalanceSheet } from "./types";

const EUR = new Intl.NumberFormat("nl-NL", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
});

function toMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function fmtDate(iso: string): string {
  const [y, m, d] = iso.split("-");
  return `${d}-${m}-${y}`;
}

function csvCell(value: string | number): string {
  const s = String(value);
  if (/["\n\r,]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function csvNumber(value: number): string {
  return value.toFixed(2).replace(".", ",");
}

function exportSheetCsv(sheet: BalanceSheet, year: number): void {
  const lines: string[] = [];
  lines.push(`Balans ${year}${sheet.as_of ? ` per ${fmtDate(sheet.as_of)}` : ""}`);
  lines.push("");
  lines.push(["Zijde", "Code", "Post", "Bedrag"].join(";"));
  const pushRows = (side: string, rows: BalanceSheet["activa"], total: number) => {
    for (const r of rows) {
      lines.push([side, String(r.code), csvCell(r.label), csvNumber(r.amount)].join(";"));
    }
    lines.push([side, "", "Totaal", csvNumber(total)].join(";"));
    lines.push("");
  };
  pushRows("Activa", sheet.activa, sheet.total_activa);
  pushRows("Passiva", sheet.passiva, sheet.total_passiva);

  const blob = new Blob(["\ufeff" + lines.join("\r\n")], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `balans-${year}${sheet.as_of ? "-" + sheet.as_of : ""}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

interface MenuItem {
  id: string;
  label: string;
  disabled?: boolean;
  onClick?: () => void;
}

function Menu({ items, label }: { items: MenuItem[]; label: string }) {
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

  if (items.length === 0) return null;

  return (
    <div className="bal-actions" ref={rootRef}>
      <button
        type="button"
        className="bal-actions-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span aria-hidden>▾</span>
        <span>{label}</span>
      </button>
      {open && (
        <ul className="bal-actions-list" role="menu">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                role="menuitem"
                disabled={item.disabled}
                onClick={() => {
                  if (item.disabled) return;
                  setOpen(false);
                  item.onClick?.();
                }}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SideTable({
  title,
  lines,
  total,
}: {
  title: string;
  lines: BalanceSheet["activa"];
  total: number;
}) {
  return (
    <section className="column">
      <h2>{title}</h2>
      <table>
        <thead>
          <tr>
            <th className="code">Code</th>
            <th>Post</th>
            <th className="num">Bedrag</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <tr key={line.category_id}>
              <td className="code">{line.code}</td>
              <td>{line.label}</td>
              <td
                className={
                  line.source === "computed" ? "num computed" : "num"
                }
              >
                {EUR.format(line.amount)}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={2}>Totaal {title}</td>
            <td className="num">{EUR.format(total)}</td>
          </tr>
        </tfoot>
      </table>
    </section>
  );
}

export default function App() {
  const [years, setYears] = useState<number[]>([]);
  const [year, setYear] = useState<number | null>(null);
  const [dates, setDates] = useState<string[]>([]);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [sheet, setSheet] = useState<BalanceSheet | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [view, setView] = useState<"sheet" | "journal">("sheet");

  const load = useCallback((y: number, date?: string | null) => {
    setError(null);
    setSheet(null);
    getSheet(y, date ?? undefined)
      .then(setSheet)
      .catch((e) => setError(toMessage(e)));
  }, []);

  useEffect(() => {
    getMeta()
      .then((m) => setTitle(m.title || ""))
      .catch(() => setTitle(""));
    getYears()
      .then((r) => {
        const ys = r.years;
        setYears(ys);
        const current = ys.length ? Math.max(...ys) : null;
        setYear(current);
        getDates(current ?? 0)
          .then((dr) => {
            setDates(dr.dates);
            if (current != null) load(current);
          })
          .catch((e) => setError(toMessage(e)));
      })
      .catch((e) => setError(toMessage(e)));
  }, [load]);

  const onYear = (y: number) => {
    setYear(y);
    setAsOf(null);
    getDates(y)
      .then((dr) => {
        setDates(dr.dates);
        load(y);
      })
      .catch((e) => setError(toMessage(e)));
  };

  const onAsOf = (d: string) => {
    setAsOf(d);
    if (year != null) load(year, d);
  };

  const onRebuild = async () => {
    if (year == null) return;
    setBusy(true);
    setError(null);
    try {
      const res = await rebuildSpaarMirror(year);
      alert(`Spaarrekening-verwerking opnieuw opgebouwd: ${res.generated} mutaties.`);
      load(year, asOf);
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const menuItems: MenuItem[] = [
    {
      id: "refresh",
      label: busy ? "Bezig…" : "Verversen",
      disabled: busy || year == null,
      onClick: onRebuild,
    },
    {
      id: "journal",
      label: "Bewerk grootboek",
      disabled: year == null,
      onClick: () => setView("journal"),
    },
    {
      id: "export-csv",
      label: "Export naar CSV",
      disabled: year == null || !sheet,
      onClick: () => {
        if (year != null && sheet) exportSheetCsv(sheet, year);
      },
    },
  ];

  return (
    <>
      {view === "journal" ? (
        <JournalEditor
          year={year ?? new Date().getFullYear()}
          onBack={() => {
            setView("sheet");
            if (year != null) load(year, asOf);
          }}
        />
      ) : (
        <div className="sheet-view">
          <header>
            <h1>
              Balans{title ? ` ${title}` : ""}
            </h1>
            {years.length > 1 && (
              <div className="year-switch">
                {years.map((y) => (
                  <button
                    key={y}
                    className={y === year ? "active" : ""}
                    onClick={() => onYear(y)}
                  >
                    {y}
                  </button>
                ))}
              </div>
            )}
            <Menu items={menuItems} label="menu" />
            {year != null && (
              <div className="toolbar">
                {dates.length > 0 && (
                  <select
                    className="asof-select"
                    value={asOf ?? ""}
                    onChange={(e) => onAsOf(e.target.value)}
                    aria-label="Toon balans per datum"
                  >
                    <option value="">Actueel</option>
                    <option value="initial">Start (vóór mutaties)</option>
                    {dates.map((d) => (
                      <option key={d} value={d}>
                        {fmtDate(d)}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}
          </header>

          {error && <div className="error">{error}</div>}

          {!sheet && !error && <div className="loading">Laden…</div>}

          {sheet && (
            <div className="sheet">
              <SideTable title="Activa" lines={sheet.activa} total={sheet.total_activa} />
              <SideTable title="Passiva" lines={sheet.passiva} total={sheet.total_passiva} />
            </div>
          )}
        </div>
      )}
    </>
  );
}
