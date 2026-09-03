import type {
  AddTermResponse,
  CatalogCategory,
  CatalogResponse,
  MatrixResponse,
  ModificationResponse,
  RefreshResponse,
  SettingsResponse,
  TermsUpdateResponse,
  Transaction,
  TransactionSplitResponse,
  TransactionsResponse,
} from "./types";

async function getJson<T>(url: string): Promise<T> {
  const resp = await fetch(url, { credentials: "include", cache: "no-store" });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
  }
  return (await resp.json()) as T;
}

async function sendJson<T>(
  url: string,
  method: "PUT" | "POST" | "PATCH" | "DELETE",
  body?: unknown
): Promise<T> {
  const init: RequestInit = {
    method,
    credentials: "include",
  };
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

export interface YearsResponse {
  years: string[];
  default_year: string;
}

export interface BanksResponse {
  folders: string[];
  multi_bank: boolean;
  show_switcher: boolean;
  upload_token?: string;
  person?: string;
  center?: string;
  year?: string;
  /** Consent active and the person has never downloaded transactions yet. */
  first_download?: boolean;
  /** PEM credentials exist but consent is not active and nothing was downloaded yet. */
  needs_initial_authorization?: boolean;
}

export function getYears(): Promise<YearsResponse> {
  return getJson("/api/years");
}

export function getBanks(year?: string): Promise<BanksResponse> {
  const q = year ? `?year=${encodeURIComponent(year)}` : "";
  return getJson(`/api/banks${q}`);
}

export function getMatrix(year?: string, bank?: string): Promise<MatrixResponse> {
  const params = new URLSearchParams();
  if (year) params.set("year", year);
  if (bank) params.set("bank", bank);
  const q = params.toString();
  return getJson(q ? `/api/matrix?${q}` : "/api/matrix");
}

export function recalculate(): Promise<MatrixResponse> {
  return sendJson("/api/recalculate", "POST", {});
}

export function recalculateFromScratch(): Promise<MatrixResponse> {
  return sendJson("/api/recalculate-from-scratch", "POST", {});
}

export function refreshAll(body: {
  date_from?: string;
  date_to?: string;
} = {}): Promise<RefreshResponse> {
  return sendJson("/api/refresh", "POST", body);
}

export function refreshPerson(
  person_name: string,
  body: {
    date_from?: string;
    date_to?: string;
    new_year?: boolean;
  } = {}
): Promise<RefreshResponse> {
  return sendJson(`/api/refresh/${encodeURIComponent(person_name)}`, "POST", body);
}

export function getTransactions(
  person_name: string,
  category: string,
  year?: string,
  bank?: string
): Promise<TransactionsResponse> {
  const params = new URLSearchParams();
  if (year) params.set("year", year);
  if (bank) params.set("bank", bank);
  const q = params.toString();
  const base = `/api/transactions/${encodeURIComponent(person_name)}/${encodeURIComponent(category)}`;
  return getJson(q ? `${base}?${q}` : base);
}

export function getCatalog(): Promise<CatalogResponse> {
  return getJson("/api/categories");
}

export function saveCatalog(
  categories: CatalogCategory[]
): Promise<CatalogResponse> {
  return sendJson("/api/categories", "PUT", { categories });
}

export function getSettings(): Promise<SettingsResponse> {
  return getJson("/api/settings");
}

export function updateSettings(
  group: string,
  category: string,
  terms: string[]
): Promise<TermsUpdateResponse> {
  return sendJson(
    `/api/settings/${encodeURIComponent(group)}/${encodeURIComponent(category)}`,
    "PUT",
    { terms }
  );
}

export function addCategoryTerm(body: {
  category_name: string;
  term: string;
  general: boolean;
  person?: string;
}): Promise<AddTermResponse> {
  return sendJson("/api/settings/add-term", "POST", body);
}

export function recordModification(
  person_name: string,
  transaction: Transaction
): Promise<ModificationResponse> {
  return sendJson(`/api/transactions/${encodeURIComponent(person_name)}/modification`, "PUT", {
    transaction,
  });
}

export function getTransactionSplit(
  person_name: string,
  id: string,
  year?: string,
  bank?: string
): Promise<TransactionSplitResponse> {
  const params = new URLSearchParams();
  params.set("id", id);
  if (year) params.set("year", year);
  if (bank) params.set("bank", bank);
  return getJson(`/api/split/${encodeURIComponent(person_name)}?${params.toString()}`);
}

export function saveTransactionSplit(
  person_name: string,
  body: {
    id: string;
    description: string;
    lines: { id?: string | null; description: string; amount: string }[];
    year?: string;
    bank?: string;
  }
): Promise<TransactionSplitResponse> {
  return sendJson(`/api/split/${encodeURIComponent(person_name)}`, "PUT", body);
}

export interface SyncNotification {
  file_path: string;
  expires_at: number;
}

export interface ConsentReadyPerson {
  person_name: string;
}

export interface CentraleSyncStatus {
  enabled: boolean;
  center: string;
  /** personal | local | country */
  access?: string;
  /** Empty / omitted = all people; otherwise only this person is visible. */
  person?: string;
  username?: string;
  title?: string;
  auth_required?: boolean;
  authenticated?: boolean;
  centrale_url: string;
  local_session_active: boolean;
  error: string | null;
  last_event_id?: number;
  notifications?: SyncNotification[];
  port?: number;
  centers?: string[];
  data_epoch?: number;
  has_secrets?: boolean;
  /** People whose bank consent just completed via hub callback. */
  consent_ready?: ConsentReadyPerson[];
}

export interface AuthMeResponse {
  auth_required: boolean;
  authenticated: boolean;
  username: string | null;
  title?: string | null;
  access?: string | null;
}

export function getAuthMe(): Promise<AuthMeResponse> {
  return getJson("/api/auth/me");
}

export function login(username: string, password: string): Promise<CentraleSyncStatus | OtpChallenge> {
  return sendJson("/api/login", "POST", { username, password });
}

export interface OtpChallenge {
  otp_required: true;
  otp_token: string;
  phone_hint: string;
  /** Present only when the hub has no Twilio config (local testing). */
  dev_code?: string;
}

export function verifyLoginOtp(otp_token: string, code: string): Promise<CentraleSyncStatus> {
  return sendJson("/api/login/otp", "POST", { otp_token, code });
}

export function resendLoginOtp(otp_token: string): Promise<OtpChallenge> {
  return sendJson("/api/login/otp/resend", "POST", { otp_token, code: "" });
}

export interface PersonSecurity {
  username: string;
  mobile_phone: string;
}

export function getPersonSecurity(): Promise<PersonSecurity> {
  return getJson("/api/auth/person-security");
}

export function setPersonPassword(body: {
  current: string;
  new_password: string;
  confirm: string;
  mobile_phone?: string;
}): Promise<{ ok: boolean; mobile_phone?: string }> {
  return sendJson("/api/auth/password", "POST", body);
}

export function logout(): Promise<{ ok: boolean; auth_required: boolean; authenticated: boolean }> {
  return sendJson("/api/logout", "POST", {});
}

export function getCentraleStatus(): Promise<CentraleSyncStatus> {
  return getJson("/api/centrale/status");
}

export function getCentraleNotifications(): Promise<{ notifications: SyncNotification[] }> {
  return getJson("/api/centrale/notifications");
}

export interface CentralWinsAlert {
  id: number;
  path: string;
  message: string;
}

export function getCentralWinsRefusals(): Promise<{ alerts: CentralWinsAlert[] }> {
  return getJson("/api/centrale/refusals");
}

export function ackCentralWinsRefusal(id: number): Promise<{
  ok: boolean;
  removed: number;
  alerts: CentralWinsAlert[];
}> {
  return sendJson("/api/centrale/refusals/ack", "POST", { id });
}

export function getCenters(): Promise<{
  centers: string[];
  center: string;
  access: string;
}> {
  return getJson("/api/centers");
}

export function setCenter(center: string): Promise<{
  ok: boolean;
  center: string;
  people: { person_name: string }[];
}> {
  return sendJson("/api/center", "POST", { center });
}

export interface IpAccessTarget {
  target: string;
  kind: string;
  label: string;
  username: string;
}

export interface IpAccessRow extends IpAccessTarget {
  ip: string;
}

export interface IpAccessResponse {
  can_edit_b: boolean;
  targets: IpAccessTarget[];
  rows: IpAccessRow[];
}

export function getIpAccess(): Promise<IpAccessResponse> {
  return getJson("/api/ip-access");
}

export function addIpAccess(body: { ip: string; target: string }): Promise<IpAccessResponse> {
  return sendJson("/api/ip-access", "POST", body);
}

export function deleteIpAccess(ip: string, target: string): Promise<IpAccessResponse> {
  const q = new URLSearchParams({ ip, target });
  return sendJson(`/api/ip-access?${q.toString()}`, "DELETE");
}
