import { useEffect, useState } from "react";
import { getAfschrijvingen, saveAfschrijvingen } from "./api";
import type { AfschrijvingCategory, AfschrijvingRow } from "./api";

type Draft = {
  key: string;
  role: number;
  fraction: string;
  local_code_van: number;
  local_code_naar: number;
};

let keySeq = 1;

const emptyBox = (defaultCode: number): Draft => ({
  key: `box-${keySeq++}`,
  role: 1,
  fraction: "",
  local_code_van: defaultCode,
  local_code_naar: defaultCode,
});

function draftFromRow(r: AfschrijvingRow): Draft {
  return {
    key: `id-${r.id}`,
    role: r.role ? 1 : 0,
    fraction: String(r.fraction),
    local_code_van: r.local_code_van,
    local_code_naar: r.local_code_naar,
  };
}

function toMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
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

function padCode(code: number): string {
  return String(code).padStart(4, "0");
}

function term(terms: Record<string, string> | undefined, key: string): string {
  const label = terms?.[key]?.trim();
  return label || key;
}

export default function AfschrijvingenEditor({
  terms,
  onBack,
}: {
  terms: Record<string, string>;
  onBack: () => void;
}) {
  const [cats, setCats] = useState<AfschrijvingCategory[]>([]);
  const [labels, setLabels] = useState<Record<number, string>>({});
  const [rows, setRows] = useState<Draft[]>([]);
  const [defaultCode, setDefaultCode] = useState<number | null>(null);
  const [box, setBox] = useState<Draft | null>(null);
  const [editKey, setEditKey] = useState<string | null>(null);
  const [filters, setFilters] = useState({ bron: "", fraction: "", van: "", naar: "" });
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    setError(null);
    getAfschrijvingen()
      .then((data) => {
        if (cancelled) return;
        const first = data.categories[0];
        if (!first) {
          setError("No dim_category rows with local_code 1000–4999");
          return;
        }
        setCats(data.categories);
        setLabels(
          Object.fromEntries(
            data.categories.map((c) => [
              c.local_code,
              `${padCode(c.local_code)} ${c.label} (${sideShort(c.side)})`,
            ])
          )
        );
        setDefaultCode(first.local_code);
        setRows(data.rows.map(draftFromRow));
        setEditKey(null);
        setBox(emptyBox(first.local_code));
        setLoaded(true);
      })
      .catch((e) => {
        if (!cancelled) setError(toMessage(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function usedCodes(): Set<number> {
    const set = new Set<number>(cats.map((c) => c.local_code));
    for (const r of rows) {
      set.add(r.local_code_van);
      set.add(r.local_code_naar);
    }
    if (box) {
      set.add(box.local_code_van);
      set.add(box.local_code_naar);
    }
    return set;
  }

  const codeOptions =
    usedCodes().size === 0
      ? []
      : [...usedCodes()]
          .sort((a, b) => a - b)
          .map((code) => (
            <option key={code} value={code}>
              {labels[code] ?? `cat_${code}`}
            </option>
          ));

  function persist(list: Draft[]): Promise<{ ok: boolean; saved: number }> {
    setError(null);
    setBusy(true);
    return saveAfschrijvingen(list.map((r) => rowToPayload(r))).finally(() => setBusy(false));
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
    if (!box || defaultCode == null) return;
    if (box.fraction === "") return;
    const next = [...rows, { ...box }];
    setRows(next);
    setBox(emptyBox(defaultCode));
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
    if (f.bron && String(r.role) !== f.bron) return false;
    if (f.van && String(r.local_code_van) !== f.van) return false;
    if (f.naar && String(r.local_code_naar) !== f.naar) return false;
    if (f.fraction && !String(r.fraction).includes(f.fraction.trim())) return false;
    return true;
  }

  const visibleRows = rows.filter(matchesFilter);

  function setFilter(key: keyof typeof filters, value: string) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <div className="journal">
      <div className="journal-bar">
        <button type="button" onClick={onBack}>
          {term(terms, "Back to summary")}
        </button>
      </div>
      <div className="journal-main">
        <aside className="journal-panel">
          <h2>{term(terms, "Automatic journal posts")}</h2>
          <div className="journal-filters">
            <label>
              Role
              <select value={filters.bron} onChange={(e) => setFilter("bron", e.target.value)}>
                <option value="">alle</option>
                <option value="1">1</option>
                <option value="0">0</option>
              </select>
            </label>
            <label>
              Fraction
              <input
                type="text"
                value={filters.fraction}
                onChange={(e) => setFilter("fraction", e.target.value)}
              />
            </label>
            <label>
              Van
              <select value={filters.van} onChange={(e) => setFilter("van", e.target.value)}>
                <option value="">alle</option>
                {codeOptions}
              </select>
            </label>
            <label>
              Naar
              <select value={filters.naar} onChange={(e) => setFilter("naar", e.target.value)}>
                <option value="">alle</option>
                {codeOptions}
              </select>
            </label>
          </div>
        </aside>
        <main className="journal-content">
          {error && <div className="error">{error}</div>}
          {loaded && box ? (
            <table className="journal-table">
              <colgroup>
                <col className="col-cat" />
                <col className="col-amount" />
                <col className="col-cat" />
                <col className="col-cat" />
                <col className="col-act" />
                <col className="col-act" />
              </colgroup>
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Fraction</th>
                  <th>Van</th>
                  <th>Naar</th>
                  <th colSpan={2}>Actie</th>
                </tr>
              </thead>
              <tbody>
                <tr className="box-line">
                  <td>
                    <input
                      type="checkbox"
                      checked={box.role === 1}
                      onChange={(e) => patchBox({ role: e.target.checked ? 1 : 0 })}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      step="0.01"
                      value={box.fraction}
                      onChange={(e) => patchBox({ fraction: e.target.value })}
                    />
                  </td>
                  <td>
                    <select
                      value={box.local_code_van}
                      onChange={(e) => patchBox({ local_code_van: Number(e.target.value) })}
                    >
                      {codeOptions}
                    </select>
                  </td>
                  <td>
                    <select
                      value={box.local_code_naar}
                      onChange={(e) => patchBox({ local_code_naar: Number(e.target.value) })}
                    >
                      {codeOptions}
                    </select>
                  </td>
                  <td colSpan={2}>
                    <button type="button" className="journal-save" disabled={busy} onClick={saveNew}>
                      {busy ? "Bezig…" : "Save"}
                    </button>
                  </td>
                </tr>
                {visibleRows.map((r) => {
                  const editing = editKey === r.key;
                  return (
                    <tr key={r.key} className={editing ? "box-line" : undefined}>
                      {editing ? (
                        <>
                          <td>
                            <input
                              type="checkbox"
                              checked={r.role === 1}
                              onChange={(e) =>
                                patchRow(r.key, { role: e.target.checked ? 1 : 0 })
                              }
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              step="0.01"
                              value={r.fraction}
                              onChange={(e) => patchRow(r.key, { fraction: e.target.value })}
                            />
                          </td>
                          <td>
                            <select
                              value={r.local_code_van}
                              onChange={(e) =>
                                patchRow(r.key, { local_code_van: Number(e.target.value) })
                              }
                            >
                              {codeOptions}
                            </select>
                          </td>
                          <td>
                            <select
                              value={r.local_code_naar}
                              onChange={(e) =>
                                patchRow(r.key, { local_code_naar: Number(e.target.value) })
                              }
                            >
                              {codeOptions}
                            </select>
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
                        </>
                      ) : (
                        <>
                          <td className="code">{r.role ? 1 : 0}</td>
                          <td className="num">{r.fraction}</td>
                          <td className="code">{padCode(r.local_code_van)}</td>
                          <td className="code">{padCode(r.local_code_naar)}</td>
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
  role: number;
  fraction: number;
  local_code_van: number;
  local_code_naar: number;
} {
  return {
    role: r.role ? 1 : 0,
    fraction: Number(r.fraction) || 0,
    local_code_van: r.local_code_van,
    local_code_naar: r.local_code_naar,
  };
}
