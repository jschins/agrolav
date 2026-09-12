import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getDates,
  getMeta,
  getPostPopup,
  getSheet,
  getSubadministratie,
  getYears,
} from "./api";
import type {
  AfschrijvingJournal,
  BalanceSheet,
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
  clickableCodes,
  onOpen,
}: {
  title: string;
  lines: BalanceSheet["activa"];
  total: number;
  clickableCodes: Set<number>;
  onOpen: (code: number, label: string) => void;
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
          {lines.map((line) => {
            const code = Number(line.code);
            return (
            <tr key={line.category_id}>
              <td className="code">{line.code}</td>
              <td>{line.label}</td>
              <td className={amountClass(line)}>
                {clickableCodes.has(code) ? (
                  <button
                    type="button"
                    className="subadmin-amount"
                    onClick={() => onOpen(code, line.label)}
                  >
                    {EUR.format(line.amount)}
                  </button>
                ) : (
                  EUR.format(line.amount)
                )}
              </td>
            </tr>
            );
          })}
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
  const [popupPeople, setPopupPeople] = useState<SubadministratieRow[]>([]);
  const [popupJournals, setPopupJournals] = useState<AfschrijvingJournal[]>([]);
  const [popupError, setPopupError] = useState<string | null>(null);
  const [popupLoading, setPopupLoading] = useState(false);

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

  const clickableCodes = useMemo(() => {
    const codes = new Set(subadminRows.map((r) => Number(r.local_code)));
    for (const code of sheet?.subadministratie?.local_codes ?? []) {
      codes.add(Number(code));
    }
    for (const code of sheet?.afschrijvingen?.from_codes ?? []) {
      codes.add(Number(code));
    }
    return codes;
  }, [sheet, subadminRows]);

  const closePopup = () => {
    setOpenCode(null);
    setPopupPeople([]);
    setPopupJournals([]);
    setPopupError(null);
    setPopupLoading(false);
  };

  const openPopup = (code: number, label: string) => {
    setOpenCode(code);
    setOpenLabel(label);
    setPopupError(null);
    setPopupLoading(true);
    const cachedPeople = [
      ...subadminRows,
      ...(sheet?.subadministratie?.rows ?? []),
    ].filter((r) => Number(r.local_code) === code);
    const cachedJournals = (sheet?.afschrijvingen?.journals ?? []).filter(
      (r) => Number(r.category_from) === code
    );
    setPopupPeople(cachedPeople);
    setPopupJournals(cachedJournals);
    if (year == null) {
      setPopupLoading(false);
      return;
    }
    getPostPopup(year, code, asOf ?? undefined)
      .then((r) => {
        if (r.people.length) setPopupPeople(r.people);
        if (r.journals.length) setPopupJournals(r.journals);
      })
      .catch((e) => setPopupError(toMessage(e)))
      .finally(() => setPopupLoading(false));
  };

  useEffect(() => {
    if (openCode == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closePopup();
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
            clickableCodes={clickableCodes}
            onOpen={openPopup}
          />
          <SideTable
            title="Passiva"
            lines={sheet.passiva}
            total={sheet.total_passiva}
            clickableCodes={clickableCodes}
            onOpen={openPopup}
          />
        </div>
      )}

      {openCode != null && (
        <div
          className="subadmin-overlay"
          role="dialog"
          aria-modal="true"
          aria-label={openLabel || "Post"}
          onClick={closePopup}
        >
          <div
            className={`subadmin-dialog${popupJournals.length ? " journal-dialog" : ""}`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="subadmin-head">
              <h2>
                {popupJournals.length ? "Journaal" : "Subadministratie"} {openCode}
                {openLabel ? ` · ${openLabel}` : ""}
              </h2>
              <button
                type="button"
                className="subadmin-close"
                aria-label="Sluiten"
                onClick={closePopup}
              >
                ✕
              </button>
            </div>
            <div className="subadmin-body">
              {popupJournals.length ? (
                <table className="subadmin-table">
                  <thead>
                    <tr>
                      <th>Datum</th>
                      <th>Van</th>
                      <th>Naar</th>
                      <th className="num">Bedrag</th>
                      <th>Omschrijving</th>
                    </tr>
                  </thead>
                  <tbody>
                    {popupJournals.map((r) => (
                      <tr key={r.journal_id}>
                        <td>{fmtDate(r.date.slice(0, 10))}</td>
                        <td>
                          {r.category_from}
                          {r.from_label ? ` ${r.from_label}` : ""}
                        </td>
                        <td>
                          {r.category_to}
                          {r.to_label ? ` ${r.to_label}` : ""}
                        </td>
                        <td className="num">{EURC.format(r.amount)}</td>
                        <td>{r.description}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : popupPeople.length ? (
                <table className="subadmin-table">
                  <thead>
                    <tr>
                      <th className="code">Code</th>
                      <th>Naam</th>
                      <th className="num">Bedrag</th>
                    </tr>
                  </thead>
                  <tbody>
                    {popupPeople.map((r) => (
                      <tr key={r.name}>
                        <td className="code">{r.local_code}</td>
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
                          popupPeople.reduce((sum, r) => sum + r.amount, 0)
                        )}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              ) : popupLoading ? (
                <p className="subadmin-empty">Laden…</p>
              ) : popupError ? (
                <p className="subadmin-empty">{popupError}</p>
              ) : (
                <p className="subadmin-empty">Geen regels.</p>
              )}
            </div>
            <div className="subadmin-foot">
              <button type="button" className="subadmin-ok" onClick={closePopup}>
                Sluiten
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
