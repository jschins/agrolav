import type {
  BalanceSheet,
  YearsResponse,
  DatesResponse,
  JournalResponse,
  JournalRow,
  CategoriesResponse,
  ResultResponse,
} from "./types";

function apiBase(): string {
  const p = window.location.pathname;
  const m = p.match(/^\/balance\/([^/]+)/);
  if (m) return `/balance/${m[1]}`;
  return "";
}

async function getJson<T>(url: string): Promise<T> {
  const resp = await fetch(apiBase() + url, {
    credentials: "include",
    cache: "no-store",
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}\n${text}`);
  }
  return (await resp.json()) as T;
}

async function postJson<T>(url: string): Promise<T> {
  const resp = await fetch(apiBase() + url, { method: "POST", credentials: "include" });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}\n${text}`);
  }
  return (await resp.json()) as T;
}

async function putJson<T>(url: string, body: unknown): Promise<T> {
  const resp = await fetch(apiBase() + url, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}\n${text}`);
  }
  return (await resp.json()) as T;
}

export function getYears(): Promise<YearsResponse> {
  return getJson("/api/balance/years");
}

export function getMeta(): Promise<{ country_id: number; slug: string; title: string }> {
  return getJson("/api/balance/meta");
}

export function getSheet(year: number, date?: string): Promise<BalanceSheet> {
  const q = date
    ? `?date=${encodeURIComponent(date)}`
    : "";
  return getJson(`/api/balance/${year}${q}`);
}

export function getResult(year: number): Promise<ResultResponse> {
  return getJson(`/api/balance/${year}/result`);
}

export function getDates(year: number): Promise<DatesResponse> {
  return getJson(`/api/balance/${year}/dates`);
}

export function rebuildSpaarMirror(year: number): Promise<{ ok: boolean; generated: number }> {
  return postJson(`/api/balance/${year}/spaar-mirror`);
}

export function getCategories(): Promise<CategoriesResponse> {
  return getJson("/api/balance/categories");
}

export function getJournal(year: number): Promise<JournalResponse> {
  return getJson(`/api/balance/${year}/journal`);
}

export function saveJournal(year: number, rows: JournalRow[]): Promise<{ ok: boolean; saved: number }> {
  const items = rows.map((r) => ({
    date: r.date,
    category_from: r.category_from,
    category_to: r.category_to,
    amount: r.amount,
    description: r.description,
  }));
  return putJson(`/api/balance/${year}/journal`, { items });
}
