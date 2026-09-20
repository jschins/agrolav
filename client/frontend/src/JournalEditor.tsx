import { useEffect, useState } from "react";
import { getJournalData, saveJournalData } from "./api";
import type { JournalRow } from "./api";

type Draft = {
  key: string;
  date: string;
  category_from: number;
  category_to: number;
  amount: string;
  description: string;
};

let keySeq = 1;

const emptyBox = (remainderId: number): Draft => ({
  key: `box-${keySeq++}`,
  date: new Date().toISOString().slice(0, 10),
  category_from: remainderId,
  category_to: remainderId,
  amount: "",
  description: "",
});

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function draftFromRow(r: JournalRow): Draft {
  return {
    key: `id-${r.journal_id}`,
    date: r.date,
    category_from: r.category_from,
    category_to: r.category_to,
    amount: String(r.amount),
    description: r.description,
  };
}

function toMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function formatDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  if (!m) return iso || "";
  return `${m[3]}-${m[2]}-${m[1]}`;
}

function sideShort(side: string): string {
  switch (side) {
    case "activa":
      return "A";
    case "passiva":
      return "P";
    case "kosten":
      return "K";
    case "opbrengsten":
      return "O";
    default:
      return side;
  }
}

function categorySelectLabel(
  cat: { code: number; label: string; side: string }
): string {
  return `${String(cat.code).padStart(4, "0")} ${cat.label} (${sideShort(cat.side)})`;
}

function term(terms: Record<string, string> | undefined, key: string): string {
  const label = terms?.[key]?.trim();
  return label || key;
}

export default function JournalEditor({
  year,
  terms,
  onBack,
}: {
  year: number;
  terms: Record<string, string>;
  onBack: () => void;
}) {
  const [cats, setCats] = useState<{ category_id: number; code: number; label: string; side: string }[]>([]);
  const [labels, setLabels] = useState<Record<number, string>>({});
  const [rows, setRows] = useState<Draft[]>([]);
  const [remainderId, setRemainderId] = useState<number | null>(null);
  const [box, setBox] = useState<Draft | null>(null);
  const [editKey, setEditKey] = useState<string | null>(null);
  const [filters, setFilters] = useState({ date: "", from: "", to: "", amount: "", desc: "" });
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    setError(null);
    getJournalData(year)
      .then((data) => {
        if (cancelled) return;
        if (data.remainder_id == null) {
          setError("No dim_category row with category_role='remainder'");
          return;
        }
        setCats(data.categories);
        setLabels(
          Object.fromEntries(
            data.categories.map((c) => [c.category_id, categorySelectLabel(c)])
          )
        );
        setRemainderId(data.remainder_id);
        setRows(data.rows.map(draftFromRow));
        setEditKey(null);
        setBox(emptyBox(data.remainder_id));
        setLoaded(true);
      })
      .catch((e) => {
        if (!cancelled) setError(toMessage(e));
      });
    return () => {
      cancelled = true;
    };
  }, [year]);

  function usedCategoryIds(): number[] {
    const set = new Set<number>(cats.map((c) => c.category_id));
    for (const r of rows) {
      set.add(r.category_from);
      set.add(r.category_to);
    }
    if (box) {
      set.add(box.category_from);
      set.add(box.category_to);
    }
    const localOf = (id: number) =>
      cats.find((c) => c.category_id === id)?.code ?? id;
    return [...set].sort((a, b) => localOf(a) - localOf(b));
  }

  const codeOptions = usedCategoryIds().map((id) => (
    <option key={id} value={id}>
      {labels[id] ?? `cat_${id}`}
    </option>
  ));

  function displayLocalCode(categoryId: number): string {
    const local = cats.find((c) => c.category_id === categoryId)?.code ?? categoryId;
    return String(local).padStart(4, "0");
  }

  function persist(list: Draft[]): Promise<{ ok: boolean; saved: number }> {
    setError(null);
    setBusy(true);
    return saveJournalData(
      year,
      list.map((r) => rowToPayload(r))
    ).finally(() => setBusy(false));
  }

  function removeRow(key: string) {
    const next = rows.filter((r) => r.key !== key);
    setRows(next);
    if (editKey === key) setEditKey(null);
    persist(next).catch((e) => setError(toMessage(e)));
  }

  function editRow(key: string) {
    setEditKey(editKey === key ? null : key);
  }

  function saveEdit() {
    persist(rows)
      .then(() => setEditKey(null))
      .catch((e) => setError(toMessage(e)));
  }

  function saveNew() {
    if (!box || remainderId == null) return;
    if (box.amount === "" && box.description.trim() === "") return;
    const next = [...rows, { ...box }];
    setRows(next);
    setBox(emptyBox(remainderId));
    persist(next).catch((e) => setError(toMessage(e)));
  }

  function patchRow(key: string, patch: Partial<Draft>) {
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  function patchBox(patch: Partial<Draft>) {
    setBox((b) => (b ? { ...b, ...patch } : b));
  }

  function matchesFilter(r: Draft): boolean {
    const f = filters;
    if (f.date && !r.date.startsWith(f.date)) return false;
    if (f.from && String(r.category_from) !== f.from) return false;
    if (f.to && String(r.category_to) !== f.to) return false;
    if (f.amount && !String(r.amount).includes(f.amount.trim())) return false;
    if (f.desc && !r.description.toLowerCase().includes(f.desc.trim().toLowerCase())) return false;
    return true;
  }

  const visibleRows = rows.filter(matchesFilter);

  function setFilter(key: keyof typeof filters, value: string) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  const maxDescLen = rows.reduce((m, r) => Math.max(m, r.description.length), 0);
  const descMinCh = Math.max(12, maxDescLen + 1);

  return (
    <div className="journal">
      <div className="journal-bar">
        <button type="button" onClick={onBack}>
          {term(terms, "Back to summary")}
        </button>
      </div>
      <div className="journal-main">
        <aside className="journal-panel">
          <h2>{term(terms, "Manual journal posts")}</h2>
          <div className="journal-filters">
            <label>
              {term(terms, "Date")}
              <input type="date" value={filters.date} onChange={(e) => setFilter("date", e.target.value)} />
            </label>
            <label>
Van ({term(terms, "Category")})
              <select value={filters.from} onChange={(e) => setFilter("from", e.target.value)}>
                <option value="">alle</option>
                {codeOptions}
              </select>
            </label>
            <label>
Naar ({term(terms, "Category")})
              <select value={filters.to} onChange={(e) => setFilter("to", e.target.value)}>
                <option value="">alle</option>
                {codeOptions}
              </select>
            </label>
            <label>
              {term(terms, "Amount")}
              <input type="text" value={filters.amount} onChange={(e) => setFilter("amount", e.target.value)} />
            </label>
            <label>
              {term(terms, "Description")}
              <input type="text" value={filters.desc} onChange={(e) => setFilter("desc", e.target.value)} />
            </label>
          </div>
        </aside>
        <main className="journal-content">
          {error && <div className="error">{error}</div>}
          {loaded && box ? (
            <table className="journal-table">
              <colgroup>
                <col className="col-date" />
                <col className="col-cat" />
                <col className="col-cat" />
                <col className="col-amount" />
                <col className="col-act" />
                <col className="col-act" />
                <col className="col-desc" />
              </colgroup>
              <thead>
                <tr>
                  <th>{term(terms, "Date")}</th>
                  <th>Van ({term(terms, "Category")})</th>
                  <th>Naar ({term(terms, "Category")})</th>
                  <th>{term(terms, "Amount")} (€)</th>
                  <th colSpan={2}>Actie</th>
                  <th>{term(terms, "Description")}</th>
                </tr>
              </thead>
              <tbody>
                <tr className="box-line">
                  <td>
                    <input type="date" value={box.date} onChange={(e) => patchBox({ date: e.target.value })} />
                  </td>
                  <td>
                    <select value={box.category_from} onChange={(e) => patchBox({ category_from: Number(e.target.value) })}>
                      {codeOptions}
                    </select>
                  </td>
                  <td>
                    <select value={box.category_to} onChange={(e) => patchBox({ category_to: Number(e.target.value) })}>
                      {codeOptions}
                    </select>
                  </td>
                  <td>
                    <input type="number" step="0.01" value={box.amount} onChange={(e) => patchBox({ amount: e.target.value })} />
                  </td>
                  <td colSpan={2}>
                    <button type="button" className="journal-save" disabled={busy} onClick={saveNew}>
                      {busy ? "Bezig…" : "Save"}
                    </button>
                  </td>
                  <td>
                    <input
                      className="journal-desc"
                      type="text"
                      style={{ minWidth: `${descMinCh}ch` }}
                      value={box.description}
                      onChange={(e) => patchBox({ description: e.target.value })}
                    />
                  </td>
                </tr>
                {visibleRows.map((r) => {
                  const editing = editKey === r.key;
                  return (
                    <tr key={r.key} className={editing ? "box-line" : undefined}>
                      {editing ? (
                        <>
                          <td>
                            <input type="date" value={r.date} onChange={(e) => patchRow(r.key, { date: e.target.value })} />
                          </td>
                          <td>
                            <select value={r.category_from} onChange={(e) => patchRow(r.key, { category_from: Number(e.target.value) })}>
                              {codeOptions}
                            </select>
                          </td>
                          <td>
                            <select value={r.category_to} onChange={(e) => patchRow(r.key, { category_to: Number(e.target.value) })}>
                              {codeOptions}
                            </select>
                          </td>
                          <td>
                            <input type="number" step="0.01" value={r.amount} onChange={(e) => patchRow(r.key, { amount: e.target.value })} />
                          </td>
                          <td colSpan={2}>
                            <button
                              type="button"
                              className="journal-save"
                              disabled={busy}
                              onClick={saveEdit}
                            >
                              {busy ? "Bezig…" : "Save"}
                            </button>
                          </td>
                          <td>
                            <input
                              className="journal-desc"
                              type="text"
                              style={{ minWidth: `${descMinCh}ch` }}
                              value={r.description}
                              onChange={(e) => patchRow(r.key, { description: e.target.value })}
                            />
                          </td>
                        </>
                      ) : (
                        <>
                          <td className="nowrap">{formatDate(r.date)}</td>
                          <td className="code">{displayLocalCode(r.category_from)}</td>
                          <td className="code">{displayLocalCode(r.category_to)}</td>
                          <td className="num">{r.amount}</td>
                          <td>
                            <button
                              type="button"
                              className="journal-x"
                              title="Verwijder"
                              onClick={() => removeRow(r.key)}
                            >
                              ×
                            </button>
                          </td>
                          <td>
                            <button type="button" className="journal-edit" onClick={() => editRow(r.key)}>
                              Edit
                            </button>
                          </td>
                          <td className="desc">{r.description}</td>
                        </>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <p>Laden…</p>
          )}
        </main>
      </div>
    </div>
  );
}

function rowToPayload(r: Draft): {
  date: string;
  category_from: number;
  category_to: number;
  amount: number;
  description: string;
} {
  return {
    date: r.date || todayIso(),
    category_from: r.category_from,
    category_to: r.category_to,
    amount: Number(r.amount) || 0,
    description: r.description.trim(),
  };
}