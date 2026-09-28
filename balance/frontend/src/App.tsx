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
  BalanceLine,
  BalanceSheet,
  CashSheet,
  SubadministratieRow,
} from "./types";
import { buildXlsx, downloadBlob, euro2, RESULT_STYLE, type XlsxCell, type XlsxSheet } from "./xlsx";

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

function requestMenuExport(): void {
  window.opener?.postMessage({ type: "agrolav-export-excel" }, "*");
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

function paint(value: string | number, style: number): XlsxCell {
  return { value, style };
}

function resultSheet(data: BalanceSheet): XlsxSheet {
  const label = new URLSearchParams(window.location.search).get("label")?.trim() || loginName();
  const title = `Resultaat${label ? ` ${label}` : ""} ${data.year}`;
  const S = RESULT_STYLE;
  const page = () => paint("", S.page);
  const rows: XlsxCell[][] = [];
  const merges: string[] = [];
  const heights: (number | undefined)[] = [];
  const push = (row: XlsxCell[], height?: number) => {
    rows.push(row);
    heights.push(height);
  };
  const at = () => rows.length + 1;

  push(
    [paint(title, S.title), paint("", S.title), paint("", S.title), paint("", S.title), paint("", S.title), paint("", S.title), paint("", S.title)],
    24
  );
  merges.push("A1:G1");
  push([page(), page(), page(), page(), page(), page(), page()], 10);

  const headRow = at();
  push(
    [
      paint("Uitgaven", S.heading),
      paint("", S.heading),
      paint("", S.heading),
      page(),
      paint("Inkomsten", S.heading),
      paint("", S.heading),
      paint("", S.heading),
    ],
    22
  );
  merges.push(`A${headRow}:C${headRow}`, `E${headRow}:G${headRow}`);
  push([
    paint("Code", S.head),
    paint("Post", S.head),
    paint("Bedrag", S.head),
    page(),
    paint("Code", S.head),
    paint("Post", S.head),
    paint("Bedrag", S.head),
  ]);

  const body = (line: BalanceLine | undefined): XlsxCell[] =>
    line
      ? [paint(String(line.code), S.code), paint(line.label, S.text), paint(euro2(line.amount), S.amount)]
      : [paint("", S.text), paint("", S.text), paint("", S.text)];
  const count = Math.max(data.activa.length, data.passiva.length);
  for (let i = 0; i < count; i += 1) {
    push([...body(data.activa[i]), page(), ...body(data.passiva[i])]);
  }

  const totalRow = at();
  push([
    paint("Totaal Uitgaven", S.total),
    paint("", S.total),
    paint(euro2(data.total_activa), S.totalAmount),
    page(),
    paint("Totaal Inkomsten", S.total),
    paint("", S.total),
    paint(euro2(data.total_passiva), S.totalAmount),
  ]);
  merges.push(`A${totalRow}:B${totalRow}`, `E${totalRow}:F${totalRow}`);

  if (data.cash) {
    push([page(), page(), page(), page(), page(), page(), page()], 14);
    const balansRow = at();
    push(
      [paint("Balans", S.heading), paint("", S.heading), paint("", S.heading), page(), page(), page(), page()],
      22
    );
    merges.push(`A${balansRow}:C${balansRow}`);
    for (const row of data.cash.rows) {
      if (row.gap) {
        push([page(), page(), page(), page(), page(), page(), page()], 10);
        continue;
      }
      const labelStyle = row.alert ? S.alert : row.strong ? S.strong : S.text;
      const amountStyle = row.alert ? S.alertAmount : row.strong ? S.strongAmount : S.amount;
      const lineRow = at();
      push([
        paint(row.label, labelStyle),
        paint("", labelStyle),
        paint(euro2(row.amount ?? 0), amountStyle),
        page(),
        page(),
        page(),
        page(),
      ]);
      merges.push(`A${lineRow}:B${lineRow}`);
    }
  }

  return {
    name: "Resultaat",
    rows,
    widths: [12, 36, 14, 3, 12, 36, 14],
    merges,
    fitPage: true,
    rowHeights: heights,
  };
}

function exportWindow(sheet: BalanceSheet, resultView: boolean): void {
  const kind = resultView ? "Resultaat" : "Balans";
  const filename = `${kind}_${safeFilePart(loginName())}_${exportStamp()}.xlsx`;
  if (resultView) {
    downloadBlob(filename, buildXlsx([resultSheet(sheet)]));
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
      <header>
        <h1>
          {resultView ? "Resultaat" : "Balans"}
          {headingName ? ` ${headingName}` : ""}
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
