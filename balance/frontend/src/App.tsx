import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  BalanceLine,
  BalanceSheet,
  CashSheet,
  SubadministratieRow,
} from "./types";
import { unitResultWorkbook } from "./resultWorkbook";
import { zipDoneLine, zipMessageLine, zipPulseLine, zipStartLines } from "./zipDebug"; // ZIP_DEBUG
import { buildXlsx, downloadBlob, euro2, type XlsxSheet } from "./xlsx";

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

function ColorNote({
  title,
  body,
  closeLabel,
  onClose,
}: {
  title: string;
  body: string;
  closeLabel: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="note-overlay" onClick={onClose}>
      <div
        className="note-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <h2>{title}</h2>
        {body ? <div className="lang-html" dangerouslySetInnerHTML={{ __html: body }} /> : null}
        <button type="button" className="note-close" onClick={onClose}>
          {closeLabel}
        </button>
      </div>
    </div>
  );
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
  journalCodes,
  subadminCodes,
  onOpen,
}: {
  title: string;
  lines: BalanceSheet["activa"];
  total: number;
  journalCodes: Set<number>;
  subadminCodes: Set<number>;
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
                {journalCodes.has(code) || subadminCodes.has(code) ? (
                  <button
                    type="button"
                    className={[
                      journalCodes.has(code) ? "journal-amount" : "",
                      subadminCodes.has(code) ? "subadmin-amount" : "",
                    ].filter(Boolean).join(" ")}
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

function isResultView(): boolean {
  return window.location.pathname.startsWith("/result/");
}

function isUnitLogin(): boolean {
  return new URLSearchParams(window.location.search).get("unit") === "1";
}

function isCountryLogin(): boolean {
  const params = new URLSearchParams(window.location.search);
  return !params.get("person") && !params.get("center") && !params.get("unit");
}

function requestMenuExport(): void {
  window.opener?.postMessage({ type: "agrolav-export-excel" }, "*");
}

type ZipRun = {
  line: string;
  log: string[];
  stepAt: number;
  done: boolean;
  error: string;
};

function ZipScreen({ run, now, onClose }: { run: ZipRun; now: number; onClose: () => void }) {
  const logRef = useRef<HTMLPreElement>(null);
  useEffect(() => {
    logRef.current?.scrollTo(0, logRef.current.scrollHeight);
  }, [run.log.length]);
  const waiting = run.done ? 0 : Math.max(0, Math.floor((now - run.stepAt) / 1000));
  return (
    <div className="zip-screen" role="status">
      <h2>{run.line}</h2>
      <p className="zip-wait">
        {run.done ? (run.error ? "Stopped" : "Download started") : `Waiting ${waiting}s on this step`}
      </p>
      <pre ref={logRef}>{run.log.join("\n")}</pre>
      {run.done ? (
        <button type="button" onClick={onClose}>
          Sluiten
        </button>
      ) : null}
    </div>
  );
}

function loginName(): string {
  return new URLSearchParams(window.location.search).get("login")?.trim() || "";
}

function exportStamp(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function safeFilePart(value: string): string {
  const text = value.trim().replace(/[\\/:*?"<>|]/g, "_");
  return text || "login";
}

function sideSheet(title: string, lines: BalanceLine[], total: number): XlsxSheet {
  const rows: XlsxSheet["rows"] = [["Code", "Post", "Bedrag"]];
  for (const line of lines) {
    rows.push([line.code, line.label, euro2(line.amount)]);
  }
  rows.push(["", `Totaal ${title}`, euro2(total)]);
  return { name: title.slice(0, 31), rows, widths: [12, 36, 16] };
}

function exportWindow(sheet: BalanceSheet, resultView: boolean): void {
  const kind = resultView ? "Resultaat" : "Balans";
  const filename = `${kind}_${safeFilePart(loginName())}_${exportStamp()}.xlsx`;
  if (resultView) {
    const label = new URLSearchParams(window.location.search).get("label")?.trim() || loginName();
    downloadBlob(filename, unitResultWorkbook(sheet, label));
    return;
  }
  const sheets = [
    sideSheet("Activa", sheet.activa, sheet.total_activa),
    sideSheet("Passiva", sheet.passiva, sheet.total_passiva),
  ];
  downloadBlob(filename, buildXlsx(sheets));
}

function CashTable({ cash }: { cash: CashSheet }) {
  return (
    <section className="column cash-block">
      <h2>Balans</h2>
      <table>
        <tbody>
          {cash.rows.map((row, index) =>
            row.gap ? (
              <tr key={index} className="gap">
                <td colSpan={2} />
              </tr>
            ) : (
              <tr
                key={index}
                className={[row.strong ? "strong" : "", row.alert ? "cash-alert" : ""]
                  .filter(Boolean)
                  .join(" ")}
              >
                <td>{row.label}</td>
                <td className="num">{EUR.format(row.amount ?? 0)}</td>
              </tr>
            )
          )}
        </tbody>
      </table>
    </section>
  );
}

export default function App() {
  const resultView = isResultView();
  const scopeLabel = new URLSearchParams(window.location.search).get("label") || "";
  const [years, setYears] = useState<number[]>([]);
  const [year, setYear] = useState<number | null>(null);
  const [dates, setDates] = useState<string[]>([]);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [sheet, setSheet] = useState<BalanceSheet | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zipRun, setZipRun] = useState<ZipRun | null>(null);
  const [zipNow, setZipNow] = useState(0);
  const zipActiveRef = useRef(false);
  const zipMessagesRef = useRef(0);
  const [title, setTitle] = useState("");
  const headingName = resultView ? scopeLabel || title : title;
  const [noteTitle, setNoteTitle] = useState("Kleurconventie");
  const [noteBody, setNoteBody] = useState("");
  const [closeLabel, setCloseLabel] = useState("Sluiten");
  const [noteOpen, setNoteOpen] = useState(false);
  const [subadminRows, setSubadminRows] = useState<SubadministratieRow[]>([]);
  const [openCode, setOpenCode] = useState<number | null>(null);
  const [openLabel, setOpenLabel] = useState("");
  const [popupPeople, setPopupPeople] = useState<SubadministratieRow[]>([]);
  const [popupJournals, setPopupJournals] = useState<AfschrijvingJournal[]>([]);
  const [popupError, setPopupError] = useState<string | null>(null);
  const [popupLoading, setPopupLoading] = useState(false);

  useEffect(() => {
    if (!zipRun || zipRun.done) return;
    const id = window.setInterval(() => setZipNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [zipRun]);

  useEffect(() => {
    // ZIP_DEBUG
    if (!zipRun || zipRun.done) return;
    const startedAt = zipRun.stepAt;
    const id = window.setInterval(() => {
      setZipRun((prev) => {
        if (!prev || prev.done) return prev;
        return {
          ...prev,
          log: [...prev.log, zipPulseLine(zipMessagesRef.current, startedAt)],
        };
      });
    }, 10000);
    return () => window.clearInterval(id);
  }, [zipRun]);

  useEffect(() => {
    function onZipMessage(event: MessageEvent) {
      const data = event.data;
      if (zipActiveRef.current) {
        // ZIP_DEBUG
        zipMessagesRef.current += 1;
        const index = zipMessagesRef.current;
        setZipRun((prev) =>
          prev ? { ...prev, log: [...prev.log, zipMessageLine(event, index)] } : prev
        );
      }
      if (data?.type === "agrolav-export-zip-progress") {
        setZipRun((prev) => ({
          line: String(data.line || prev?.line || "Export zip"),
          log: prev?.log ?? [],
          stepAt: Date.now(),
          done: false,
          error: "",
        }));
        setZipNow(Date.now());
        return;
      }
      if (data?.type !== "agrolav-export-zip-done") return;
      const failure = data.error ? String(data.error) : "";
      if (failure) setError(failure);
      zipActiveRef.current = false;
      setZipRun((prev) => ({
        line: failure ? "Export zip failed" : "Export zip finished",
        log: [...(prev?.log ?? []), zipDoneLine(failure)], // ZIP_DEBUG
        stepAt: Date.now(),
        done: true,
        error: failure,
      }));
    }
    window.addEventListener("message", onZipMessage);
    return () => window.removeEventListener("message", onZipMessage);
  }, []);

  const load = useCallback((y: number, date?: string | null) => {
    setError(null);
    setSheet(null);
    getSheet(y, date ?? undefined)
      .then(setSheet)
      .catch((e) => setError(toMessage(e)));
  }, []);

  useEffect(() => {
    getMeta()
      .then((m) => {
        setTitle(m.title || "");
        if (m.color_convention_title) setNoteTitle(m.color_convention_title);
        if (m.color_convention_body) setNoteBody(m.color_convention_body);
        if (m.close_label) setCloseLabel(m.close_label);
      })
      .catch(() => setTitle(""));
    getSubadministratie()
      .then((r) => setSubadminRows(r.rows))
      .catch(() => setSubadminRows([]));
    getYears()
      .then((r) => {
        const ys = r.years;
        setYears(ys);
        const current =
          r.default_year != null && ys.includes(r.default_year)
            ? r.default_year
            : ys.length
              ? Math.max(...ys)
              : null;
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

  const journalCodes = useMemo(() => {
    const codes = new Set<number>();
    for (const code of sheet?.afschrijvingen?.from_codes ?? []) {
      codes.add(Number(code));
    }
    return codes;
  }, [sheet]);

  const subadminCodes = useMemo(() => {
    const codes = new Set(subadminRows.map((r) => Number(r.local_code)));
    for (const code of sheet?.subadministratie?.local_codes ?? []) {
      codes.add(Number(code));
    }
    return codes;
  }, [sheet, subadminRows]);

  const balanceJournalCodes = useMemo(() => {
    const codes = new Set<number>();
    for (const code of sheet?.balance?.afschrijvingen?.from_codes ?? []) {
      codes.add(Number(code));
    }
    return codes;
  }, [sheet]);

  const balanceSubadminCodes = useMemo(() => {
    const codes = new Set(subadminRows.map((r) => Number(r.local_code)));
    for (const code of sheet?.balance?.subadministratie?.local_codes ?? []) {
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
    const seen = new Set<string>();
    const cachedPeople = subadminRows
      .filter((r) => Number(r.local_code) === code)
      .filter((r) => {
        if (seen.has(r.name)) return false;
        seen.add(r.name);
        return true;
      })
      .sort((a, b) => a.name.localeCompare(b.name));
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
    let channel: BroadcastChannel | null = null;
    try {
      channel = new BroadcastChannel("agrolav-balance");
      channel.onmessage = (e: MessageEvent) => {
        if (e.data?.type === "agrolav-close") window.close();
      };
    } catch {
      // ignore
    }
    window.addEventListener("message", onMessage);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("message", onMessage);
      window.removeEventListener("keydown", onKey);
      channel?.close();
    };
  }, [openCode]);

  return (
    <div className="sheet-view">
      {zipRun ? (
        <ZipScreen
          run={zipRun}
          now={zipNow || Date.now()}
          onClose={() => setZipRun(null)}
        />
      ) : null}
      <header>
        <h1>
          {resultView ? "Resultaat" : "Balans"}
          {headingName ? ` ${headingName}` : ""}
        </h1>
        {resultView && year != null && years.length > 0 ? (
          <select
            className="year-select"
            value={year}
            onChange={(e) => onYear(Number(e.target.value))}
            aria-label="Jaar"
          >
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        ) : years.length > 1 ? (
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
        ) : null}
        {year != null && (
          <div className="toolbar">
            {dates.length > 0 && (
              <select
                className="asof-select"
                value={asOf ?? ""}
                onChange={(e) => onAsOf(e.target.value)}
                aria-label={resultView ? "Toon resultaat per datum" : "Toon balans per datum"}
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
            <button
              type="button"
              className="info-knob"
              onClick={() => setNoteOpen(true)}
            >
              {noteTitle}
            </button>
            {resultView && (
              <button
                type="button"
                className="export-knob"
                disabled={!sheet}
                onClick={() => {
                  if (!sheet) return;
                  if (isUnitLogin()) exportWindow(sheet, true);
                  else requestMenuExport();
                }}
              >
                Export
              </button>
            )}
            {resultView && isCountryLogin() && (
              <button
                type="button"
                className="export-knob"
                disabled={Boolean(zipRun && !zipRun.done)}
                onClick={() => {
                  if (zipRun && !zipRun.done) return;
                  setError(null);
                  setZipNow(Date.now());
                  zipMessagesRef.current = 0; // ZIP_DEBUG
                  zipActiveRef.current = true; // ZIP_DEBUG
                  setZipRun({
                    line: "Export zip",
                    log: zipStartLines(year), // ZIP_DEBUG
                    stepAt: Date.now(),
                    done: false,
                    error: "",
                  });
                }}
              >
                Export zip
              </button>
            )}
          </div>
        )}
      </header>

      {noteOpen ? (
        <ColorNote
          title={noteTitle}
          body={noteBody}
          closeLabel={closeLabel}
          onClose={() => setNoteOpen(false)}
        />
      ) : null}

      {error && <div className="error">{error}</div>}

      {!sheet && !error && <div className="loading">Laden…</div>}

      {sheet && (
        <div className="sheet">
          <SideTable
            title={resultView ? "Uitgaven" : "Activa"}
            lines={sheet.activa}
            total={sheet.total_activa}
            journalCodes={journalCodes}
            subadminCodes={subadminCodes}
            onOpen={openPopup}
          />
          <SideTable
            title={resultView ? "Inkomsten" : "Passiva"}
            lines={sheet.passiva}
            total={sheet.total_passiva}
            journalCodes={journalCodes}
            subadminCodes={subadminCodes}
            onOpen={openPopup}
          />
        </div>
      )}

      {resultView && sheet?.balance ? (
        <section className="balance-below">
          <h2>Balans</h2>
          <div className="sheet">
            <SideTable
              title="Activa"
              lines={sheet.balance.activa}
              total={sheet.balance.total_activa}
              journalCodes={balanceJournalCodes}
              subadminCodes={balanceSubadminCodes}
              onOpen={openPopup}
            />
            <SideTable
              title="Passiva"
              lines={sheet.balance.passiva}
              total={sheet.balance.total_passiva}
              journalCodes={balanceJournalCodes}
              subadminCodes={balanceSubadminCodes}
              onOpen={openPopup}
            />
          </div>
        </section>
      ) : null}
      {resultView && sheet?.balance_error ? (
        <div className="error">{sheet.balance_error}</div>
      ) : null}

      {resultView && sheet?.cash ? <CashTable cash={sheet.cash} /> : null}

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
                {popupJournals.length && popupPeople.length
                  ? "Journaal en subadministratie"
                  : popupJournals.length
                    ? "Journaal"
                    : "Subadministratie"}{" "}
                {openCode}
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
              ) : null}
              {popupPeople.length ? (
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
              ) : null}
              {!popupJournals.length && !popupPeople.length ? (
                popupLoading ? (
                  <p className="subadmin-empty">Laden…</p>
                ) : popupError ? (
                  <p className="subadmin-empty">{popupError}</p>
                ) : (
                  <p className="subadmin-empty">Geen regels.</p>
                )
              ) : null}
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
