import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getCategoryTransactions,
  getDates,
  getMeta,
  getSheet,
  getSubadministratie,
  getYears,
} from "./api";
import type {
  BalanceSheet,
  CategoryTransactionRow,
  SubadministratieRow,
} from "./types";

const EUR = new Intl.NumberFormat("nl-NL", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
});

const EURC = new Intl.NumberFormat("nl-NL", {
  style: "currency",
  currency: "EUR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function toMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function fmtDate(iso: string): string {
  const [y, m, d] = iso.split("-");
  return `${d}-${m}-${y}`;
}

function isPlug(line: BalanceSheet["activa"][number]): boolean {
  return (
    line.role === "equity" ||
    line.source === "computed" ||
    line.unchanged === true ||
    line.unchanged === false
  );
}

function amountClass(line: BalanceSheet["activa"][number]): string {
  if (!isPlug(line)) return "num";
  return line.unchanged === true ? "num plug-still" : "num plug-moved";
}

function SideTable({
  title,
  lines,
  total,
  subadminCodes,
  onOpenSubadmin,
}: {
  title: string;
  lines: BalanceSheet["activa"];
  total: number;
  subadminCodes: Set<number>;
  onOpenSubadmin: (code: number, label: string) => void;
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
              <td className={amountClass(line)}>
                {subadminCodes.has(line.code) ? (
                  <button
                    type="button"
                    className="subadmin-amount"
                    onClick={() => onOpenSubadmin(line.code, line.label)}
                  >
                    {EUR.format(line.amount)}
                  </button>
                ) : (
                  EUR.format(line.amount)
                )}
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
  const [title, setTitle] = useState("");
  const [subadminRows, setSubadminRows] = useState<SubadministratieRow[]>([]);
  const [openCode, setOpenCode] = useState<number | null>(null);
  const [openLabel, setOpenLabel] = useState("");
  const [txRows, setTxRows] = useState<CategoryTransactionRow[]>([]);
  const [txError, setTxError] = useState<string | null>(null);
  const [txLoading, setTxLoading] = useState(false);

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
    getSubadministratie()
      .then((r) => setSubadminRows(r.rows))
      .catch(() => setSubadminRows([]));
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

  const subadminCodes = useMemo(
    () => new Set(subadminRows.map((r) => r.local_code)),
    [subadminRows]
  );

  const openSubadmin = (code: number, label: string) => {
    setOpenCode(code);
    setOpenLabel(label);
    setTxRows([]);
    setTxError(null);
    setTxLoading(true);
    if (year == null) return;
    getCategoryTransactions(year, code, asOf ?? undefined)
      .then((r) => setTxRows(r.rows))
      .catch((e) => setTxError(toMessage(e)))
      .finally(() => setTxLoading(false));
  };

  useEffect(() => {
    if (openCode == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenCode(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openCode]);

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.data?.type === "agrolav-close") {
        if (e.source === window.opener) window.close();
      }
      if (e.data?.type === "agrolav-probe") {
        try {
          if (window.opener) {
            window.opener.postMessage({ type: "agrolav-pong" }, "*");
          }
        } catch {
          // ignore
        }
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || openCode != null) return;
      try {
        window.opener?.postMessage({ type: "agrolav-focus-front" }, "*");
      } catch {
        // ignore
      }
      try {
        window.opener?.focus();
      } catch {
        // ignore
      }
      window.close();
    };
    window.addEventListener("message", onMessage);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("message", onMessage);
      window.removeEventListener("keydown", onKey);
    };
  }, [openCode]);

  const openRows =
    openCode != null
      ? subadminRows.filter((r) => r.local_code === openCode)
      : [];

  const combinedRows = useMemo(() => {
    const byName = new Map<string, number>();
    for (const r of openRows) {
      byName.set(r.name, (byName.get(r.name) ?? 0) + r.amount);
    }
    for (const r of txRows) {
      byName.set(r.name, (byName.get(r.name) ?? 0) + r.amount);
    }
    return Array.from(byName, ([name, amount]) => ({
      key: name,
      code: openCode ?? 0,
      name,
      amount,
    })).sort((a, b) => a.name.localeCompare(b.name, "nl"));
  }, [openRows, txRows, openCode]);

  return (
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

      {sheet?.plug_debug && (
        <aside className="plug-debug" aria-label="2000 debug">
          <h2>2000 debug</h2>
          <dl>
            <div>
              <dt>balance_opening</dt>
              <dd>{sheet.plug_debug.opening}</dd>
            </div>
            <div>
              <dt>calculated</dt>
              <dd>{sheet.plug_debug.calculated}</dd>
            </div>
            <div>
              <dt>equal</dt>
              <dd>{sheet.plug_debug.equal ? "yes" : "no"}</dd>
            </div>
          </dl>
        </aside>
      )}

      {sheet && (
        <div className="sheet">
          <SideTable
            title="Activa"
            lines={sheet.activa}
            total={sheet.total_activa}
            subadminCodes={subadminCodes}
            onOpenSubadmin={openSubadmin}
          />
          <SideTable
            title="Passiva"
            lines={sheet.passiva}
            total={sheet.total_passiva}
            subadminCodes={subadminCodes}
            onOpenSubadmin={openSubadmin}
          />
        </div>
      )}

      {openCode != null && (
        <div
          className="subadmin-overlay"
          role="dialog"
          aria-modal="true"
          aria-label="Subadministratie"
          onClick={() => setOpenCode(null)}
        >
          <div className="subadmin-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="subadmin-head">
              <h2>
                Subadministratie {openCode}
                {openLabel ? ` · ${openLabel}` : ""}
              </h2>
              <button
                type="button"
                className="subadmin-close"
                aria-label="Sluiten"
                onClick={() => setOpenCode(null)}
              >
                ✕
              </button>
            </div>
            <div className="subadmin-body">
              {combinedRows.length ? (
                <table className="subadmin-table">
                  <thead>
                    <tr>
                      <th className="code">Code</th>
                      <th>Naam</th>
                      <th className="num">Bedrag</th>
                    </tr>
                  </thead>
                  <tbody>
                    {combinedRows.map((r) => (
                      <tr key={r.key}>
                        <td className="code">{r.code}</td>
                        <td>{r.name}</td>
                        <td className="num">{EURC.format(r.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td colSpan={2}>Totaal</td>
                      <td className="num">
                        {EURC.format(
                          combinedRows.reduce((sum, r) => sum + r.amount, 0)
                        )}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              ) : txLoading ? (
                <p className="subadmin-empty">Laden…</p>
              ) : txError ? (
                <p className="subadmin-empty">{txError}</p>
              ) : (
                <p className="subadmin-empty">Geen regels.</p>
              )}
            </div>
            <div className="subadmin-foot">
              <button
                type="button"
                className="subadmin-ok"
                onClick={() => setOpenCode(null)}
              >
                Sluiten
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
