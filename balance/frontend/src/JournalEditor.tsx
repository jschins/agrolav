import { useEffect, useState } from "react";
import { getJournal, saveJournal, getCategories } from "./api";
import type { CategoryInfo, JournalRow } from "./types";

type Draft = {
  key: string;
  date: string;
  category_from: number;
  category_to: number;
  amount: string;
  description: string;
};

let keySeq = 1;

const emptyBox = (): Draft => ({
  key: `box-${keySeq++}`,
  date: new Date().toISOString().slice(0, 10),
  category_from: 1000,
  category_to: 2000,
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

export default function JournalEditor({
  year,
  onBack,
}: {
  year: number;
  onBack: () => void;
}) {
  const [cats, setCats] = useState<CategoryInfo[]>([]);
  const [labels, setLabels] = useState<Record<number, string>>({});
  const [rows, setRows] = useState<Draft[]>([]);
  const [box, setBox] = useState<Draft>(emptyBox);
  const [editKey, setEditKey] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getCategories()
      .then((d) => {
        if (cancelled) return;
        setCats(d.categories);
        setLabels(
          Object.fromEntries(d.categories.map((c) => [c.code, `${String(c.code).padStart(4, "0")} ${c.label} (${c.side})`]))
        );
      })
      .catch(() => {});
    getJournal(year)
      .then((d) => {
        if (cancelled) return;
        setRows(d.rows.map(draftFromRow));
        setEditKey(null);
        setBox(emptyBox());
        setLoaded(true);
      })
      .catch((e) => {
        if (!cancelled) setError(toMessage(e));
      });
    return () => {
      cancelled = true;
    };
  }, [year]);

  function usedCodes(): Set<number> {
    const set = new Set<number>([...cats.map((c) => c.code)]);
    for (const r of rows) {
      set.add(r.category_from);
      set.add(r.category_to);
    }
    set.add(box.category_from);
    set.add(box.category_to);
    return set;
  }

  const codeOptions = [...usedCodes()]
    .sort((a, b) => a - b)
    .map((code) => (
      <option key={code} value={code}>
        {labels[code] ?? `cat_${code}`}
      </option>
    ));

  function persist(list: Draft[]): Promise<{ ok: boolean; saved: number }> {
    setError(null);
    setBusy(true);
    return saveJournal(
      year,
      list.map((r) => rowToPayload(r, year))
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
    if (box.amount === "" && box.description.trim() === "") return;
    const next = [...rows, { ...box }];
    setRows(next);
    setBox(emptyBox());
    persist(next).catch((e) => setError(toMessage(e)));
  }

  function patchRow(key: string, patch: Partial<Draft>) {
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  function patchBox(patch: Partial<Draft>) {
    setBox((b) => ({ ...b, ...patch }));
  }

  const maxDescLen = rows.reduce((m, r) => Math.max(m, r.description.length), 0);
  const descMinCh = Math.max(12, maxDescLen + 1);

  return (
    <div className="journal">
      <div className="journal-bar">
        <button type="button" onClick={onBack}>
          Terug naar balans
        </button>
      </div>
      <div className="journal-main">
        <aside className="journal-panel">
          <h2>Bewerk grootboek</h2>
        </aside>
        <main className="journal-content">
          {error && <div className="error">{error}</div>}
          {loaded ? (
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
                  <th>Datum</th>
                  <th>Van (C)</th>
                  <th>Naar (C)</th>
                  <th>Bedrag</th>
                  <th colSpan={2}>Actie</th>
                  <th>Omschrijving</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
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
                          <td className="code">{String(r.category_from).padStart(4, "0")}</td>
                          <td className="code">{String(r.category_to).padStart(4, "0")}</td>
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

function rowToPayload(r: Draft, year: number): JournalRow {
  return {
    journal_id: 0,
    year,
    date: r.date || todayIso(),
    category_from: r.category_from,
    category_to: r.category_to,
    amount: Number(r.amount) || 0,
    description: r.description.trim(),
    from_label: "",
    to_label: "",
  };
}
