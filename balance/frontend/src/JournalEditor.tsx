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

export default function JournalEditor({
  year,
  onBack,
}: {
  year: number;
  onBack: () => void;
}) {
  const [cats, setCats] = useState<CategoryInfo[]>([]);
  const [labels, setLabels] = useState<Record<number, string>>({});
  const [draft, setDraft] = useState<Draft[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

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
        setDraft(d.rows.map(draftFromRow));
        setLoaded(true);
      })
      .catch((e) => {
        if (!cancelled) setError(toMessage(e));
      });
    return () => {
      cancelled = true;
    };
  }, [year]);

  function patch(key: string, patch: Partial<Draft>) {
    setSaved(false);
    setDraft((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  function addRow() {
    setSaved(false);
    const codes = usedCodes().size ? [...usedCodes()].sort((a, b) => a - b) : [1000, 2000];
    const from = codes[0];
    const to = codes.find((c) => c !== from) ?? 2000;
    setDraft((rows) => [
      ...rows,
      {
        key: `new-${keySeq++}`,
        date: todayIso(),
        category_from: from,
        category_to: to,
        amount: "",
        description: "",
      },
    ]);
  }

  function removeRow(key: string) {
    setSaved(false);
    setDraft((rows) => rows.filter((r) => r.key !== key));
  }

  function submit() {
    setError(null);
    setBusy(true);
    setSaved(false);
    const payload: JournalRow[] = draft
      .map((r) => ({
        journal_id: 0,
        year,
        date: r.date || todayIso(),
        category_from: r.category_from,
        category_to: r.category_to,
        amount: Number(r.amount) || 0,
        description: r.description.trim(),
        from_label: "",
        to_label: "",
      }))
      .filter((r) => r.description !== "" || r.amount !== 0);
    saveJournal(year, payload)
      .then(() => setSaved(true))
      .catch((e) => setError(toMessage(e)))
      .finally(() => setBusy(false));
  }

  function usedCodes(): Set<number> {
    const set = new Set<number>([...cats.map((c) => c.code)]);
    for (const r of draft) {
      set.add(r.category_from);
      set.add(r.category_to);
    }
    return set;
  }

  const codeOptions = [...usedCodes()]
    .sort((a, b) => a - b)
    .map((code) => (
      <option key={code} value={code}>
        {labels[code] ?? `cat_${code}`}
      </option>
    ));

  return (
    <div className="journal">
      <div className="journal-side">
        <button type="button" onClick={onBack}>
          Balans
        </button>
        <button type="button" onClick={addRow}>
          Regel toevoegen
        </button>
        <button type="button" disabled={busy} onClick={submit}>
          {busy ? "Bezig…" : "Opslaan"}
        </button>
      </div>
      <div className="journal-body">
        {error && <div className="error">{error}</div>}
        {saved && <div className="ok">Opgeslagen. Ga terug naar de balans om de totalen te zien.</div>}
        {loaded ? (
          <table className="journal-table">
            <thead>
              <tr>
                <th>Datum</th>
                <th>Van (categorie)</th>
                <th>Naar (categorie)</th>
                <th>Bedrag</th>
                <th>Omschrijving</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {draft.map((r) => (
                <tr key={r.key}>
                  <td>
                    <input
                      type="date"
                      value={r.date}
                      onChange={(e) => patch(r.key, { date: e.target.value })}
                    />
                  </td>
                  <td>
                    <select
                      value={r.category_from}
                      onChange={(e) => patch(r.key, { category_from: Number(e.target.value) })}
                    >
                      {codeOptions}
                    </select>
                  </td>
                  <td>
                    <select
                      value={r.category_to}
                      onChange={(e) => patch(r.key, { category_to: Number(e.target.value) })}
                    >
                      {codeOptions}
                    </select>
                  </td>
                  <td>
                    <input
                      type="number"
                      step="0.01"
                      value={r.amount}
                      onChange={(e) => patch(r.key, { amount: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      type="text"
                      value={r.description}
                      onChange={(e) => patch(r.key, { description: e.target.value })}
                    />
                  </td>
                  <td>
                    <button type="button" className="journal-delete" onClick={() => removeRow(r.key)}>
                      Verwijder
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p>Laden…</p>
        )}
      </div>
    </div>
  );
}
