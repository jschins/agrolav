const API = "/maaltijden/api";

async function getJson<T>(url: string): Promise<T> {
  const resp = await fetch(url, { credentials: "include", cache: "no-store" });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
  }
  return (await resp.json()) as T;
}

async function sendJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "include" };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const resp = await fetch(url, init);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
  }
  return (await resp.json()) as T;
}

export interface Session {
  ok: boolean;
  authenticated: boolean;
  username: string;
  title: string;
  access: string;
  person: string;
  center: string;
  country: string;
  is_admin?: boolean;
}

export function login(username: string, password: string): Promise<Session> {
  return sendJson(`${API}/login`, "POST", { username, password });
}

export function logout(): Promise<{ ok: boolean; authenticated: boolean }> {
  return sendJson(`${API}/logout`, "POST");
}

export function getMe(): Promise<Session> {
  return getJson(`${API}/me`);
}

export interface WeekDay {
  weekday: number;
  date: string;
  day: number;
  month: number;
  month_name: string;
  dag: string;
}

export interface MonthSpan {
  month: number;
  name: string;
  span: number;
}

export interface PersonRow {
  person_id: number;
  username: string;
  title: string;
}

export interface WeekOption {
  sunday: string;
  week: number;
  label: string;
}

export interface ExtraDay {
  O: number;
  M: number;
  A: number;
  L: number;
  P: number;
}

export interface WeekData {
  sunday: string;
  week: number;
  year: number;
  days: WeekDay[];
  months: MonthSpan[];
  meals: string[];
  dagen: string[];
  people: PersonRow[];
  marks: Record<string, string>;
  extra: ExtraDay[];
  me: {
    person_id: number | null;
    username: string;
    access: string;
    can_edit_all: boolean;
    is_admin: boolean;
    can_edit_extra: boolean;
  };
  weeks: WeekOption[];
}

export function getWeek(sunday?: string): Promise<WeekData> {
  const q = sunday ? `?sunday=${encodeURIComponent(sunday)}` : "";
  return getJson(`${API}/week${q}`);
}

export function saveMark(body: {
  sunday: string;
  weekday: number;
  meal: string;
  mark: string;
  person_id: number;
}): Promise<{ ok: boolean; mark: string }> {
  return sendJson(`${API}/mark`, "PUT", body);
}

export function saveExtra(body: {
  sunday: string;
  weekday: number;
} & ExtraDay): Promise<{ ok: boolean; weekday: number }> {
  return sendJson(`${API}/extra`, "PUT", body);
}

export function markKey(personId: number, weekday: number, meal: string): string {
  return `${personId}:${weekday}:${meal}`;
}
