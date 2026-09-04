import type { BalanceSheet, YearsResponse } from "./types";

function apiBase(): string {
  const p = window.location.pathname;
  if (p.startsWith("/balance/") || p === "/balance") return "/balance";
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

export function getYears(): Promise<YearsResponse> {
  return getJson("/api/balance/years");
}

export function getSheet(year: number): Promise<BalanceSheet> {
  return getJson(`/api/balance/${year}`);
}

export function rebuildSpaarMirror(year: number): Promise<{ ok: boolean; generated: number }> {
  return postJson(`/api/balance/${year}/spaar-mirror`);
}
