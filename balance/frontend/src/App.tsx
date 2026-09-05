import { useCallback, useEffect, useState } from "react";
import { getMeta, getSheet, getYears, rebuildSpaarMirror } from "./api";
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
  const [sheet, setSheet] = useState<BalanceSheet | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [view, setView] = useState<"sheet" | "journal">("sheet");

  const load = useCallback((y: number) => {
    setError(null);
    setSheet(null);
    getSheet(y)
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
        if (current != null) load(current);
      })
      .catch((e) => setError(toMessage(e)));
  }, [load]);

  const onRebuild = async () => {
    if (year == null) return;
    setBusy(true);
    setError(null);
    try {
      const res = await rebuildSpaarMirror(year);
      alert(`Spaarrekening-verwerking opnieuw opgebouwd: ${res.generated} mutaties.`);
      load(year);
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {view === "journal" ? (
        <JournalEditor
          year={year ?? new Date().getFullYear()}
          onBack={() => {
            setView("sheet");
            if (year != null) load(year);
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
                    onClick={() => {
                      setYear(y);
                      load(y);
                    }}
                  >
                    {y}
                  </button>
                ))}
              </div>
            )}
          </header>

          {sheet && (
            <div className="toolbar">
              <button onClick={onRebuild} disabled={busy || year == null}>
                {busy ? "Bezig…" : "Verversen"}
              </button>
              <button onClick={() => setView("journal")} disabled={year == null}>
                Bewerk grootboek
              </button>
            </div>
          )}

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
