import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent, type MouseEvent, type ReactNode } from "react";
import { flushSync } from "react-dom";
import {
  ackCentralWinsRefusal,
  addCategoryTerm,
  getAuthMe,
  getCentralWinsRefusals,
  getCentraleNotifications,
  getCentraleStatus,
  getBanks,
  getCatalog,
  getIpAccess,
  addIpAccess,
  deleteIpAccess,
  type IpAccessResponse,
  type IpAccessTarget,
  getMatrix,
  getSettings,
  getTransactions,
  getYears,
  login,
  logout,
  verifyLoginOtp,
  resendLoginOtp,
  getPersonSecurity,
  setPersonPassword,
  type OtpChallenge,
  recalculate,
  recalculateFromScratch,
  wipeYear,
  recordModification,
  refreshAll,
  refreshPerson,
  saveCatalog,
  getTransactionSplit,
  saveTransactionSplit,
  setCenter,
  updateSettings,
  type CentralWinsAlert,
  type CentraleSyncStatus,
  type SyncNotification,
} from "./api";
import type {
  CatalogCategory,
  MatrixResponse,
  PersonInfo,
  RefreshPersonResult,
  SettingsResponse,
  Transaction,
  TransactionsResponse,
} from "./types";

const CHANNEL = "boekhouding";
const REFRESH_STATUS_KEY = "boekhouding-refresh-status";

function matrixFooterNames(matrix: MatrixResponse): { balance: string; last_booked: string } {
  return {
    balance: matrix.footers?.balance ?? "saldo",
    last_booked: matrix.footers?.last_booked ?? "datum",
  };
}

function isBookingCategoryName(name: string): boolean {
  return /^\d{4}/.test(name);
}

function shownLabel(localCode: number, label: string): string {
  const pad = localCode < 100 ? 2 : 4;
  return `${String(localCode).padStart(pad, "0")} ${label}`;
}

function displayCategoryName(name: string): string {
  const match = String(name).match(/^(\d{4}) (.*)$/);
  if (!match) return name;
  return shownLabel(parseInt(match[1], 10), match[2]);
}

function csvEscape(value: string): string {
  if (/[",\n\r]/.test(value)) return `"${value.replace(/"/g, '""')}"`;
  return value;
}

function matrixToProfitLossCsv(matrix: MatrixResponse): string {
  const people = matrix.people.map((p) => p.person_name);
  const header = ["Category", ...people].map(csvEscape).join(",");
  const rows = matrix.categories.map((cat) => {
    const amounts = people.map((name) => csvEscape(matrix.cells[cat]?.[name] ?? ""));
    return [csvEscape(displayCategoryName(cat)), ...amounts].join(",");
  });
  return [header, ...rows].join("\r\n") + "\r\n";
}

function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function isMatrixFooter(matrix: MatrixResponse, category: string): boolean {
  const footers = matrixFooterNames(matrix);
  return category === footers.balance || category === footers.last_booked;
}

function categoryCodeFromName(name: string): number | null {
  const match = String(name).match(/^(\d{4})/);
  if (!match) return null;
  return parseInt(match[1], 10);
}

function patchDetail(
  detail: TransactionsResponse,
  patch: {
    removeId?: string;
    update?: Transaction;
    blueId?: string;
    boldId?: string;
  }
): TransactionsResponse {
  let transactions = detail.transactions;
  if (patch.removeId) {
    transactions = transactions.filter((row) => String(row.id) !== patch.removeId);
  } else if (patch.update) {
    const id = String(patch.update.id ?? "");
    transactions = transactions.map((row) => (String(row.id) === id ? patch.update! : row));
  }
  const descriptionIds = new Set(detail.description_modified_ids ?? []);
  const categoryIds = new Set(detail.category_modified_ids ?? []);
  if (patch.blueId) descriptionIds.add(patch.blueId);
  if (patch.boldId) categoryIds.add(patch.boldId);
  return {
    ...detail,
    transactions,
    description_modified_ids: [...descriptionIds],
    category_modified_ids: [...categoryIds],
  };
}

type HeaderAction = {
  id: string;
  label: string;
  disabled?: boolean;
  onClick?: () => void;
};

type AppView = "main" | "terms" | "categories" | "ip" | "split" | "password";

const VIEW_CHANGE_EVENT = "boekhouding-view";

const HeaderActionsContext = createContext<(items: HeaderAction[]) => void>(() => {});

type StoredRefreshStatus = {
  results: RefreshPersonResult[];
  warnings: string[];
};

type RefreshStatusScope = {
  center: string;
  person: string;
};

function refreshStatusStorageKey(scope?: RefreshStatusScope | null): string {
  if (scope?.center && scope?.person) {
    return `${REFRESH_STATUS_KEY}:${scope.center}:${scope.person}`;
  }
  return REFRESH_STATUS_KEY;
}

function parseStoredRefreshStatus(raw: string | null): StoredRefreshStatus | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as StoredRefreshStatus | string;
    // Older builds stored a plain string summary.
    if (typeof parsed === "string") {
      return { results: [], warnings: [parsed] };
    }
    if (parsed && Array.isArray(parsed.results)) {
      return {
        results: parsed.results,
        warnings: Array.isArray(parsed.warnings) ? parsed.warnings : [],
      };
    }
  } catch {
    /* ignore */
  }
  return null;
}

function filterRefreshStatusForPerson(
  stored: StoredRefreshStatus | null,
  person: string,
): StoredRefreshStatus | null {
  if (!stored || !person) return stored;
  const needle = person.trim().toLowerCase();
  return {
    results: stored.results.filter(
      (r) => String(r.person_name || "").trim().toLowerCase() === needle
    ),
    warnings: stored.warnings.filter((w) => {
      const lower = w.toLowerCase();
      return lower.startsWith(`${needle}:`) || lower.startsWith(`${needle} (`);
    }),
  };
}

function loadStoredRefreshStatus(scope?: RefreshStatusScope | null): StoredRefreshStatus | null {
  try {
    const scoped = parseStoredRefreshStatus(
      sessionStorage.getItem(refreshStatusStorageKey(scope))
    );
    if (scoped) return scoped;
    if (scope?.person) {
      // Drop stale global status from another personal login in the same tab.
      sessionStorage.removeItem(REFRESH_STATUS_KEY);
    }
    return parseStoredRefreshStatus(sessionStorage.getItem(REFRESH_STATUS_KEY));
  } catch {
    /* ignore */
  }
  return null;
}

function saveStoredRefreshStatus(
  payload: StoredRefreshStatus,
  scope?: RefreshStatusScope | null,
): void {
  try {
    sessionStorage.setItem(refreshStatusStorageKey(scope), JSON.stringify(payload));
    if (scope?.center && scope?.person) {
      sessionStorage.removeItem(REFRESH_STATUS_KEY);
    }
  } catch {
    /* ignore */
  }
}

function clearStoredRefreshStatus(scope?: RefreshStatusScope | null): void {
  try {
    if (scope?.center && scope?.person) {
      sessionStorage.removeItem(refreshStatusStorageKey(scope));
      return;
    }
    // Clear every refresh-status key so one login cannot leak into the next.
    const doomed: string[] = [];
    for (let i = 0; i < sessionStorage.length; i += 1) {
      const key = sessionStorage.key(i);
      if (key && (key === REFRESH_STATUS_KEY || key.startsWith(`${REFRESH_STATUS_KEY}:`))) {
        doomed.push(key);
      }
    }
    for (const key of doomed) {
      sessionStorage.removeItem(key);
    }
  } catch {
    /* ignore */
  }
}

const REFRESH_BUSY_EVENTS = ["keydown", "keyup", "keypress", "contextmenu"] as const;
const refreshBusyListenerOpts: AddEventListenerOptions = { capture: true };
let refreshBusyBlock: ((e: Event) => void) | null = null;

function blockRefreshBusyEvent(e: Event): void {
  e.preventDefault();
  e.stopPropagation();
}

function beginRefreshBusy(message = "please wait... processing"): void {
  document.documentElement.style.setProperty("--busy-message", JSON.stringify(message));
  document.documentElement.classList.add("refresh-busy");
  if (refreshBusyBlock) return;
  refreshBusyBlock = blockRefreshBusyEvent;
  for (const type of REFRESH_BUSY_EVENTS) {
    window.addEventListener(type, blockRefreshBusyEvent, refreshBusyListenerOpts);
  }
  window.addEventListener("wheel", blockRefreshBusyEvent, { capture: true, passive: false });
}

function endRefreshBusy(): void {
  document.documentElement.classList.remove("refresh-busy");
  if (!refreshBusyBlock) return;
  refreshBusyBlock = null;
  for (const type of REFRESH_BUSY_EVENTS) {
    window.removeEventListener(type, blockRefreshBusyEvent, refreshBusyListenerOpts);
  }
  window.removeEventListener("wheel", blockRefreshBusyEvent, refreshBusyListenerOpts);
}

function afterPaint(fn: () => void): () => void {
  let cancelled = false;
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      if (!cancelled) fn();
    });
  });
  return () => {
    cancelled = true;
  };
}

type CellSelection = { person_name: string; category: string };

function CenterSwitcher({
  center,
  centers,
  onSelect,
}: {
  center: string;
  centers: string[];
  onSelect: (ws: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(ev: Event) {
      if (!rootRef.current?.contains(ev.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="center-switcher" ref={rootRef}>
      <button
        type="button"
        className="center-switcher-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="center-switcher-chevron" aria-hidden>
          ▾
        </span>
        <span className="center-switcher-label">{center}</span>
      </button>
      {open && (
        <ul className="center-switcher-menu" role="listbox">
          {centers.map((ws) => (
            <li key={ws}>
              <button
                type="button"
                role="option"
                aria-selected={ws === center}
                className={ws === center ? "is-selected" : undefined}
                onClick={() => {
                  setOpen(false);
                  if (ws !== center) onSelect(ws);
                }}
              >
                {ws}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BankSwitcher({
  view,
  folders,
  onSelect,
}: {
  view: string;
  folders: string[];
  onSelect: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const options = ["consolidated", ...folders.filter((f) => f !== "consolidated")];

  useEffect(() => {
    if (!open) return;
    function onDoc(ev: Event) {
      if (!rootRef.current?.contains(ev.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="center-switcher" ref={rootRef}>
      <button
        type="button"
        className="center-switcher-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="center-switcher-chevron" aria-hidden>
          ▾
        </span>
        <span className="center-switcher-label">{view}</span>
      </button>
      {open && (
        <ul className="center-switcher-menu" role="listbox">
          {options.map((name) => (
            <li key={name}>
              <button
                type="button"
                role="option"
                aria-selected={name === view}
                className={name === view ? "is-selected" : undefined}
                onClick={() => {
                  setOpen(false);
                  if (name !== view) onSelect(name);
                }}
              >
                {name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function YearSwitcher({
  year,
  years,
  onSelect,
}: {
  year: string;
  years: string[];
  onSelect: (y: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(ev: Event) {
      if (!rootRef.current?.contains(ev.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="center-switcher" ref={rootRef}>
      <button
        type="button"
        className="center-switcher-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="center-switcher-chevron" aria-hidden>
          ▾
        </span>
        <span className="center-switcher-label">{year}</span>
      </button>
      {open && (
        <ul className="center-switcher-menu" role="listbox">
          {years.map((y) => (
            <li key={y}>
              <button
                type="button"
                role="option"
                aria-selected={y === year}
                className={y === year ? "is-selected" : undefined}
                onClick={() => {
                  setOpen(false);
                  if (y !== year) onSelect(y);
                }}
              >
                {y}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ActionsMenu({ items }: { items: HeaderAction[] }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(ev: Event) {
      if (!rootRef.current?.contains(ev.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  if (items.length === 0) return null;

  return (
    <div className="center-switcher actions-menu" ref={rootRef}>
      <button
        type="button"
        className="center-switcher-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="center-switcher-chevron" aria-hidden>
          ▾
        </span>
        <span className="center-switcher-label">menu</span>
      </button>
      {open && (
        <ul className="center-switcher-menu" role="menu">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                role="menuitem"
                disabled={item.disabled}
                onClick={() => {
                  if (item.disabled) return;
                  setOpen(false);
                  item.onClick?.();
                }}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SyncNotifyShell({
  children,
  onCenterChanged,
  termsView = false,
  categoriesView = false,
  ipView = false,
  splitView = false,
  passwordView = false,
  onLogout,
  initialTitle = "",
}: {
  children: (
    brandName: string,
    activeYear: string,
    bankView: string,
    dataRev: number,
    banks: { person?: string; first_download: boolean; needs_initial_authorization: boolean }
  ) => ReactNode;
  onCenterChanged?: () => void;
  termsView?: boolean;
  categoriesView?: boolean;
  ipView?: boolean;
  splitView?: boolean;
  passwordView?: boolean;
  onLogout?: () => void;
  initialTitle?: string;
}) {
  const [status, setStatus] = useState<CentraleSyncStatus | null>(null);
  const [notes, setNotes] = useState<SyncNotification[]>([]);
  const [switching, setSwitching] = useState(false);
  const [activeYear, setActiveYear] = useState<string>("");
  const [yearOptions, setYearOptions] = useState<string[]>([]);
  const [bankView, setBankView] = useState<string>("consolidated");
  const [bankOptions, setBankOptions] = useState<string[]>([]);
  const [showBankSwitcher, setShowBankSwitcher] = useState(false);
  const [uploadUrl, setUploadUrl] = useState<string>("");
  const [refusal, setRefusal] = useState<CentralWinsAlert | null>(null);
  const [headerActions, setHeaderActions] = useState<HeaderAction[]>([]);
  const [scratchBusy, setScratchBusy] = useState(false);
  const [scratchError, setScratchError] = useState<string | null>(null);
  const [wipeBusy, setWipeBusy] = useState(false);
  const [wipeError, setWipeError] = useState<string | null>(null);
  const [dataRev, setDataRev] = useState(0);
  const dataEpochRef = useRef<number | null>(null);

  const [banksState, setBanksState] = useState<{
    person?: string;
    first_download: boolean;
    needs_initial_authorization: boolean;
  }>({ first_download: false, needs_initial_authorization: false });

  const brandName = (status?.title || initialTitle || "").trim();

  useEffect(() => {
    getYears()
      .then((res) => {
        setYearOptions(res.years);
        setActiveYear((prev) => {
          if (prev && res.years.includes(prev)) return prev;
          if (res.years.includes(res.default_year)) return res.default_year;
          if (res.years.length > 0) return res.years[res.years.length - 1];
          return res.default_year;
        });
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.center]);

  useEffect(() => {
    const access = (status?.access || "").trim().toLowerCase();
    if (access !== "personal" || !activeYear) {
      setShowBankSwitcher(false);
      setBankOptions([]);
      setBankView("consolidated");
      setUploadUrl("");
      setBanksState({ first_download: false, needs_initial_authorization: false });
      return;
    }
    let cancelled = false;
    function loadBanks() {
      getBanks(activeYear)
        .then((res) => {
          if (cancelled) return;
          const hub = (status?.centrale_url || "").replace(/\/$/, "");
          const token = (res.upload_token || "").trim();
          const person = (res.person || status?.person || "").trim();
          const center = (res.center || status?.center || "").trim();
          let nextUrl = "";
          if (hub && token) {
            const qs = new URLSearchParams({ t: token });
            if (person) qs.set("person", person);
            if (center) qs.set("center", center);
            nextUrl = `${hub}/upload?${qs.toString()}`;
          }
          setUploadUrl(nextUrl);
          setShowBankSwitcher(
            Boolean(res.show_switcher) || (res.folders || []).length > 1
          );
          setBankOptions(res.folders || []);
          setBankView((prev) => {
            if (prev === "consolidated") return prev;
            if ((res.folders || []).includes(prev)) return prev;
            return "consolidated";
          });
          setBanksState({
            person: person || undefined,
            first_download: res.first_download === true,
            needs_initial_authorization: res.needs_initial_authorization === true,
          });
        })
        .catch(() => {
          if (cancelled) return;
          setShowBankSwitcher(false);
          setBankOptions([]);
          setUploadUrl("");
          setBanksState({
            first_download: false,
            needs_initial_authorization: false,
          });
        });
    }
    loadBanks();
    const id = window.setInterval(loadBanks, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [status?.access, activeYear, status?.center, status?.person, status?.centrale_url]);

  useEffect(() => {
    if (!brandName) return;
    document.title = termsView
      ? `${brandName} — Terms`
      : categoriesView
        ? `${brandName} — Categories`
        : ipView
          ? `${brandName} — IP access`
          : passwordView
            ? `${brandName} — Password`
            : brandName;
  }, [brandName, termsView, categoriesView, ipView, passwordView]);

  useEffect(() => {
    let cancelled = false;
    function poll() {
      getCentraleStatus()
        .then((s) => {
          if (cancelled) return;
          setStatus(s);
          const epoch = typeof s.data_epoch === "number" ? s.data_epoch : null;
          if (epoch != null) {
            if (dataEpochRef.current == null) {
              dataEpochRef.current = epoch;
            } else if (epoch > dataEpochRef.current) {
              dataEpochRef.current = epoch;
              setDataRev((n) => n + 1);
            }
          }
        })
        .catch(() => {});
      getCentraleNotifications()
        .then((payload) => {
          if (!cancelled) setNotes(payload.notifications || []);
        })
        .catch(() => {});
      getCentralWinsRefusals()
        .then((payload) => {
          if (cancelled) return;
          const next = (payload.alerts || [])[0] || null;
          setRefusal((prev) => {
            if (prev && next && prev.id === next.id) return prev;
            return next;
          });
        })
        .catch(() => {});
    }
    poll();
    const id = window.setInterval(poll, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [onCenterChanged]);

  const access = (status?.access || "").trim().toLowerCase();
  const isCountry = access === "country";
  // Country login always shows the switcher, even for a single center.
  const centers = isCountry
    ? status?.centers?.length
      ? status.centers
      : status?.center
        ? [status.center]
        : []
    : [];

  function handleSelect(ws: string) {
    if (!isCountry) return;
    setSwitching(true);
    setCenter(ws)
      .then(() => getCentraleStatus())
      .then((s) => {
        setStatus(s);
        const epoch = typeof s.data_epoch === "number" ? s.data_epoch : null;
        if (epoch != null) dataEpochRef.current = epoch;
        onCenterChanged?.();
      })
      .catch(() => {})
      .finally(() => setSwitching(false));
  }

  function dismissRefusal() {
    if (!refusal) return;
    const id = refusal.id;
    ackCentralWinsRefusal(id)
      .then((res) => {
        const next = (res.alerts || [])[0] || null;
        setRefusal(next);
        onCenterChanged?.();
      })
      .catch(() => {
        setRefusal(null);
        onCenterChanged?.();
      });
  }

  function doRecalculateFromScratch() {
    if (scratchBusy || wipeBusy) return;
    beginRefreshBusy("please wait... recalculating categories");
    flushSync(() => {
      setScratchBusy(true);
      setScratchError(null);
    });
    afterPaint(() => {
      recalculateFromScratch()
        .then(() => {
          onCenterChanged?.();
        })
        .catch((e: Error) => setScratchError(e.message))
        .finally(() => {
          setScratchBusy(false);
          endRefreshBusy();
        });
    });
  }

  function exportProfitLoss() {
    if (!activeYear) return;
    setScratchError(null);
    const bankQuery = bankView !== "consolidated" ? bankView : undefined;
    getMatrix(activeYear, bankQuery)
      .then((payload) => {
        const suffix = bankQuery ? `-${bankQuery}` : "";
        downloadCsv(`profit-loss-${activeYear}${suffix}.csv`, matrixToProfitLossCsv(payload));
      })
      .catch((e: Error) => setScratchError(e.message));
  }

  function doWipeYear() {
    if (scratchBusy || wipeBusy) return;
    const suggested = activeYear || String(new Date().getFullYear());
    const raw = window.prompt("Year to wipe (YYYY)", suggested);
    if (raw == null) return;
    const year = raw.trim();
    if (!/^\d{4}$/.test(year) || Number(year) < 1990 || Number(year) > 2100) {
      setWipeError("Enter a four-digit year between 1990 and 2100");
      return;
    }
    const ok = window.confirm(
      `Delete every ${year} transaction for all accounts in this country? Uploaded file names for those accounts will also be removed. This cannot be undone.`
    );
    if (!ok) return;
    beginRefreshBusy(`please wait... wiping ${year}`);
    flushSync(() => {
      setWipeBusy(true);
      setWipeError(null);
    });
    afterPaint(() => {
      wipeYear(year)
        .then(() => {
          onCenterChanged?.();
        })
        .catch((e: Error) => setWipeError(e.message))
        .finally(() => {
          setWipeBusy(false);
          endRefreshBusy();
        });
    });
  }

  const showBar =
    Boolean(status?.enabled) ||
    isCountry ||
    headerActions.length > 0 ||
    Boolean(uploadUrl) ||
    Boolean(onLogout);

  const menuItems = useMemo(() => {
    const items = [...headerActions];
    items.push({
      id: "terms",
      label: "⚙ Edit Terms (Alt+T)",
      onClick: () => openView("terms"),
    });
    items.push({
      id: "recalculate-categories",
      label: scratchBusy ? "Recalculating…" : "Recalculate categories",
      disabled: scratchBusy || wipeBusy,
      onClick: doRecalculateFromScratch,
    });
    if (activeYear && !termsView && !categoriesView && !ipView && !splitView && !passwordView) {
      items.push({
        id: "export-profit-loss",
        label: "Export Profit-Loss",
        onClick: exportProfitLoss,
      });
    }
    if (access === "country") {
      items.push({
        id: "wipe-year",
        label: wipeBusy ? "Wiping…" : "Wipe year",
        disabled: scratchBusy || wipeBusy,
        onClick: doWipeYear,
      });
    }
    if (access === "country" || access === "local") {
      items.push({
        id: "categories",
        label: "Edit categories",
        onClick: () => openView("categories"),
      });
      items.push({
        id: "ip-access",
        label: "Restrict IP access",
        onClick: () => openView("ip"),
      });
    }
    if (access === "personal") {
      items.push({
        id: "set-password",
        label: "Set password",
        onClick: () => openView("password"),
      });
    }
    if (uploadUrl) {
      items.push({
        id: "upload",
        label: "Upload",
        onClick: () => window.location.assign(uploadUrl),
      });
    }
    if (onLogout) {
      items.push({
        id: "logout",
        label: "Logout",
        onClick: onLogout,
      });
    }
    return items;
  }, [headerActions, uploadUrl, access, scratchBusy, wipeBusy, onLogout, activeYear, bankView, termsView, categoriesView, ipView, splitView, passwordView]);

  return (
    <HeaderActionsContext.Provider value={setHeaderActions}>
    <div className="lock-shell">
      {showBar && (
        <div className="centrale-status-bar">
          <div className="centrale-status-left">
            {isCountry ? (
              <CenterSwitcher
                center={status?.center || "…"}
                centers={centers}
                onSelect={handleSelect}
              />
            ) : null}
            {!termsView && !categoriesView && !ipView && !splitView && !passwordView && activeYear ? (
              <YearSwitcher
                year={activeYear}
                years={yearOptions}
                onSelect={(y) => {
                  setActiveYear(y);
                  onCenterChanged?.();
                }}
              />
            ) : null}
            {showBankSwitcher && !termsView && !categoriesView && !ipView && !splitView && !passwordView ? (
              <BankSwitcher
                view={bankView}
                folders={bankOptions}
                onSelect={(v) => {
                  setBankView(v);
                  onCenterChanged?.();
                }}
              />
            ) : null}
            {!passwordView ? <ActionsMenu items={menuItems} /> : null}
            {switching ? <span className="center-switcher-busy">switching…</span> : null}
            {scratchError ? <span> · {scratchError}</span> : null}
            {wipeError ? <span> · {wipeError}</span> : null}
            {status?.error ? <span> · sync error: {status.error}</span> : null}
          </div>
          <div className="sync-notify-row">
            {notes.map((n) => (
              <button key={`${n.file_path}-${n.expires_at}`} type="button" className="sync-notify-btn">
                {n.file_path}
              </button>
            ))}
          </div>
        </div>
      )}
      {refusal && !isCountry && (
        <div className="central-wins-overlay" role="alertdialog" aria-modal="true">
          <div className="central-wins-dialog">
            <p>{refusal.message}</p>
            {refusal.path ? <p className="central-wins-path">{refusal.path}</p> : null}
            <button type="button" className="central-wins-ok" onClick={dismissRefusal}>
              OK
            </button>
          </div>
        </div>
      )}
      {children(brandName, activeYear, bankView, dataRev, banksState)}
    </div>
    </HeaderActionsContext.Provider>
  );
}

function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function formatTermMatchHint(typerules: { type: string; category: string }[]): string {
  const priority =
    "Priority (highest first): (1) typerules beat all keywords; " +
    "(2) personal beats all general; " +
    "(3) && terms beat single-phrase terms; " +
    "(4) last-stick: later category name, then later term, wins.";
  const wildcards =
    "# matches zero or more letters or dots within one word (not across spaces). " +
    "Use && when both phrases must match (e.g. albert && heijn).";
  const rules =
    typerules.length === 0
      ? ""
      : ` Typerules: ${typerules.map((rule) => `${rule.type} → ${displayCategoryName(rule.category)}`).join("; ")}.`;
  return `${wildcards} ${priority}${rules}`;
}

function tableHeaderTerm(
  terms: Record<string, string> | undefined,
  key: string,
  fallback?: string
): string {
  const label = terms?.[key]?.trim();
  if (label) return label;
  return fallback ?? key;
}

const COLUMN_HEADER_KEYS: Record<string, string> = {
  amount: "Amount",
  type: "Type",
  name: "Name",
  iban: "IBAN",
  description: "Description",
  date: "Date",
  category: "C",
};

function columnHeaderLabel(
  column: string,
  terms: Record<string, string> | undefined
): string {
  const key = COLUMN_HEADER_KEYS[column] ?? column;
  return tableHeaderTerm(terms, key);
}

function abbreviate(map: Record<string, string>, type: unknown): string {
  const t = String(type ?? "");
  if (map[t]) return map[t];
  const lower = t.toLowerCase();
  for (const [key, value] of Object.entries(map)) {
    if (key.toLowerCase() === lower) return value;
  }
  return t;
}

function parseAppView(search = window.location.search): AppView {
  const view = new URLSearchParams(search).get("view");
  if (
    view === "terms" ||
    view === "categories" ||
    view === "ip" ||
    view === "split" ||
    view === "password"
  ) {
    return view;
  }
  return "main";
}

function viewUrl(target: "main" | "terms" | "categories" | "ip" | "password"): string {
  if (target === "terms") return `${window.location.pathname}?view=terms`;
  if (target === "categories") return `${window.location.pathname}?view=categories`;
  if (target === "ip") return `${window.location.pathname}?view=ip`;
  if (target === "password") return `${window.location.pathname}?view=password`;
  return window.location.pathname;
}

function showInThisWindow(url: string) {
  const next = new URL(url, window.location.href);
  const there = `${next.pathname}${next.search}`;
  const here = `${window.location.pathname}${window.location.search}`;
  if (here === there) return;
  window.history.pushState({}, "", there);
  window.dispatchEvent(new Event(VIEW_CHANGE_EVENT));
}

function openView(target: "main" | "terms" | "categories" | "ip" | "password") {
  showInThisWindow(viewUrl(target));
}

function clearViewParam() {
  if (!new URLSearchParams(window.location.search).has("view")) return;
  const url = new URL(window.location.href);
  url.searchParams.delete("view");
  window.history.replaceState({}, "", url.toString());
}

function isPlainAlt(e: KeyboardEvent): boolean {
  if (!e.altKey || e.ctrlKey || e.metaKey) return false;
  const el = e.target as HTMLElement | null;
  return !(
    el &&
    (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)
  );
}

export default function App() {
  const [appView, setAppView] = useState<AppView>(parseAppView);
  const isTerms = appView === "terms";
  const isCategories = appView === "categories";
  const isIp = appView === "ip";
  const isSplit = appView === "split";
  const isPassword = appView === "password";
  const [wsEpoch, setWsEpoch] = useState(0);
  const [authRequired, setAuthRequired] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [heading, setHeading] = useState("");
  const bumpCenterEpoch = useCallback(() => setWsEpoch((n) => n + 1), []);

  useEffect(() => {
    const sync = () => setAppView(parseAppView());
    window.addEventListener(VIEW_CHANGE_EVENT, sync);
    window.addEventListener("popstate", sync);
    return () => {
      window.removeEventListener(VIEW_CHANGE_EVENT, sync);
      window.removeEventListener("popstate", sync);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    getAuthMe()
      .then((me) => {
        if (cancelled) return;
        setAuthRequired(me.auth_required);
        setAuthenticated(me.authenticated);
        setHeading((me.title || "").trim());
        setAuthChecked(true);
      })
      .catch(() => {
        if (cancelled) return;
        setAuthRequired(false);
        setAuthenticated(true);
        setAuthChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!authChecked) {
    return <div className="login-screen"><p className="login-muted">Loading…</p></div>;
  }

  if (authRequired && !authenticated) {
    return (
      <LoginScreen
        onSuccess={(title) => {
          setHeading(title);
          setAuthenticated(true);
          setWsEpoch((n) => n + 1);
          // A fresh login always starts on the matrix-of-totals view, not on a
          // leftover ?view=terms|categories|ip|split tab that a previous session
          // may have left open (or a stale URL the user reused).
          clearViewParam();
          setAppView("main");
        }}
      />
    );
  }

  return (
    <SyncNotifyShell
      initialTitle={heading}
      termsView={isTerms}
      categoriesView={isCategories}
      ipView={isIp}
      splitView={isSplit}
      passwordView={isPassword}
      onLogout={
        authRequired
          ? () => {
              logout()
                .then(() => {
                  clearStoredRefreshStatus();
                  setAuthenticated(false);
                })
                .catch(() => {
                  clearStoredRefreshStatus();
                  setAuthenticated(false);
                });
            }
          : undefined
      }
      onCenterChanged={bumpCenterEpoch}
    >
      {(brandName, year, bankView, dataRev, banks) =>
        isTerms ? (
          <TermsApp key={wsEpoch} />
        ) : isCategories ? (
          <CategoriesApp key={wsEpoch} />
        ) : isIp ? (
          <IpAccessApp key={wsEpoch} />
        ) : isPassword ? (
          <SetPasswordApp key={wsEpoch} />
        ) : isSplit ? (
          <SplitApp key={wsEpoch} />
        ) : (
          <MainApp
            key={wsEpoch}
            brandName={brandName}
            year={year}
            bankView={bankView}
            dataRev={dataRev}
            banks={banks}
          />
        )
      }
    </SyncNotifyShell>
  );
}

function isOtpChallenge(
  status: CentraleSyncStatus | OtpChallenge | null | undefined
): status is OtpChallenge {
  if (!status || typeof status !== "object") return false;
  const token = "otp_token" in status ? String(status.otp_token || "").trim() : "";
  if (!token) return false;
  if ("username" in status && String(status.username || "").trim()) return false;
  return true;
}

function LoginScreen({ onSuccess }: { onSuccess: (title: string) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [otp, setOtp] = useState<OtpChallenge | null>(null);
  const [code, setCode] = useState("");

  function fail(err: Error) {
    const text = err.message || "";
    if (text.includes("401")) {
      setError(otp ? "Invalid or expired code" : "Invalid username or password");
    } else if (text.includes("403")) {
      setError("This login is not allowed from your IP address");
    } else if (text.includes("429")) {
      setError(text.replace(/^\d+\s+\w+:\s*/, ""));
    } else {
      setError(text);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    if (otp) {
      verifyLoginOtp(otp.otp_token, code.trim())
        .then((status) => {
          clearStoredRefreshStatus();
          onSuccess((status.title || "").trim());
        })
        .catch(fail)
        .finally(() => setBusy(false));
      return;
    }
    login(username.trim(), password)
      .then((status) => {
        if (isOtpChallenge(status)) {
          setOtp(status);
          setCode("");
          return;
        }
        clearStoredRefreshStatus();
        onSuccess((status.title || "").trim());
      })
      .catch(fail)
      .finally(() => setBusy(false));
  }

  function resend() {
    if (!otp) return;
    setBusy(true);
    setError(null);
    resendLoginOtp(otp.otp_token)
      .then((next) => {
        setOtp(next);
        setCode("");
      })
      .catch(fail)
      .finally(() => setBusy(false));
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <h1 className="login-title">Expenses</h1>
        {otp ? (
          <>
            <p className="login-muted">
              {otp.dev_code
                ? `SMS is not configured on the hub. Use code ${otp.dev_code}.`
                : `Enter the code sent to ${otp.phone_hint || "your mobile phone"}.`}
            </p>
            <label className="login-label">
              Code
              <input
                className="login-input"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                disabled={busy}
                required
              />
            </label>
            {error ? <p className="login-error">{error}</p> : null}
            <button className="login-submit" type="submit" disabled={busy}>
              {busy ? "Checking…" : "Verify"}
            </button>
            <button
              className="login-submit"
              type="button"
              disabled={busy}
              onClick={resend}
              style={{ background: "#fff", color: "#0e7490" }}
            >
              Resend code
            </button>
            <button
              className="login-submit"
              type="button"
              disabled={busy}
              onClick={() => {
                setOtp(null);
                setCode("");
                setError(null);
              }}
              style={{ background: "#fff", color: "#0e7490" }}
            >
              Back
            </button>
          </>
        ) : (
          <>
            <label className="login-label">
              Username
              <input
                className="login-input"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={busy}
                required
              />
            </label>
            <label className="login-label">
              Password
              <input
                className="login-input"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={busy}
                required
              />
            </label>
            {error ? <p className="login-error">{error}</p> : null}
            <button className="login-submit" type="submit" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </>
        )}
      </form>
    </div>
  );
}

const HEADING_MIN_PX = 11;

function FitSidebarTitle({ text }: { text: string }) {
  const ref = useRef<HTMLHeadingElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    const fit = () => {
      el.style.fontSize = "";
      const maxPx = parseFloat(getComputedStyle(el).fontSize);
      if (!Number.isFinite(maxPx) || maxPx <= 0) return;
      const avail = el.clientWidth;
      if (avail <= 0 || el.scrollWidth <= avail) return;
      let size = Math.max(HEADING_MIN_PX, Math.floor((maxPx * avail) / el.scrollWidth));
      el.style.fontSize = `${size}px`;
      while (el.scrollWidth > el.clientWidth && size > HEADING_MIN_PX) {
        size -= 1;
        el.style.fontSize = `${size}px`;
      }
    };

    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [text]);

  return (
    <h1 ref={ref} className="app-heading">
      {text}
    </h1>
  );
}

function MainApp({
  brandName,
  year,
  bankView,
  dataRev,
  banks,
}: {
  brandName: string;
  year: string;
  bankView: string;
  dataRev: number;
  banks?: { person?: string; first_download: boolean; needs_initial_authorization: boolean };
}) {
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null);
  const [selection, setSelection] = useState<CellSelection | null>(null);
  const [detail, setDetail] = useState<TransactionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [firstDownloading, setFirstDownloading] = useState(false);
  const [consentReady, setConsentReady] = useState<Record<string, boolean>>({});
  const [refreshScope, setRefreshScope] = useState<RefreshStatusScope | null>(null);
  const [refreshStatus, setRefreshStatus] = useState<StoredRefreshStatus | null>(null);
  const [hasSecrets, setHasSecrets] = useState(false);
  const [canAddPerson, setCanAddPerson] = useState(false);
  const [addPersonUrl, setAddPersonUrl] = useState<string | null>(null);
  const [termMenu, setTermMenu] = useState<{
    term: string;
    x: number;
    y: number;
    transactionId: string;
  } | null>(null);
  const [termMenuSettings, setTermMenuSettings] = useState<SettingsResponse | null>(null);
  const selectionRef = useRef<CellSelection | null>(null);
  const dirtyRef = useRef(false);
  const viewInitRef = useRef(false);

  useEffect(() => {
    getCentraleStatus()
      .then((s) => {
        setHasSecrets(Boolean(s.has_secrets));
        const scoped = Boolean((s.person || "").trim());
        setCanAddPerson(!scoped);
        const hub = (s.centrale_url || "").replace(/\/$/, "");
        const ws = (s.center || "").trim();
        if (hub && ws) {
          setAddPersonUrl(`${hub}/add-person?center=${encodeURIComponent(ws)}`);
        } else if (hub) {
          setAddPersonUrl(`${hub}/add-person`);
        } else {
          setAddPersonUrl(null);
        }
        // Personal login: restore this person's refresh status only (no auto-fetch).
        const person = (s.person || "").trim();
        const scope =
          scoped && ws && person ? { center: ws, person } : null;
        setRefreshScope(scope);
        const stored = loadStoredRefreshStatus(scope);
        const scopedStored =
          scope?.person ? filterRefreshStatusForPerson(stored, scope.person) : stored;
        setRefreshStatus(scopedStored);
      })
      .catch(() => {
        setHasSecrets(false);
        setCanAddPerson(false);
        setAddPersonUrl(null);
      });
  }, []);

  useEffect(() => {
    const awaitingAuth = (refreshStatus?.results || []).some(
      (r) => r.skipped && r.reason === "needs_consent_renewal"
    );
    if (!awaitingAuth) {
      setConsentReady({});
      return;
    }
    let cancelled = false;
    function pollReady() {
      getCentraleStatus()
        .then((s) => {
          if (cancelled) return;
          const next: Record<string, boolean> = {};
          for (const item of s.consent_ready || []) {
            const person_name = (item.person_name || "").trim();
            if (person_name) next[person_name] = true;
          }
          setConsentReady(next);
        })
        .catch(() => {});
    }
    pollReady();
    const id = window.setInterval(pollReady, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [refreshStatus]);

  useEffect(() => {
    selectionRef.current = selection;
  }, [selection]);

  const bankAuthRequired =
    banks?.needs_initial_authorization === true && Boolean(banks?.person);
  const bankAuthAutoRef = useRef(false);
  useEffect(() => {
    if (!bankAuthRequired) return;
    if (bankAuthAutoRef.current) return;
    const person_name = banks?.person || "";
    if (!person_name) return;
    let cancelled = false;
    let tries = 0;
    function attempt() {
      if (cancelled) return;
      if (hasSecrets) {
        bankAuthAutoRef.current = true;
        doFirstDownload(person_name);
        return;
      }
      tries += 1;
      if (tries < 10 && !cancelled) window.setTimeout(attempt, 300);
    }
    attempt();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bankAuthRequired, hasSecrets]);

  useEffect(() => {
    return () => endRefreshBusy();
  }, []);

  function clearDirty() {
    dirtyRef.current = false;
  }

  const bankQuery = bankView !== "consolidated" ? bankView : undefined;

  function loadDetail(
    person_name: string,
    category: string,
    { quiet = false }: { quiet?: boolean } = {}
  ): Promise<void> {
    if (!quiet) setDetail(null);
    return getTransactions(person_name, category, year, bankQuery)
      .then(setDetail)
      .catch((e: Error) => setError(e.message));
  }

  function loadDisplay(
    sel: CellSelection | null,
    { quiet = false }: { quiet?: boolean } = {}
  ): Promise<void> {
    setError(null);
    return getMatrix(year, bankQuery)
      .then((payload) => {
        setMatrix(payload);
        if (!sel) {
          if (!quiet) setDetail(null);
          return;
        }
        return loadDetail(sel.person_name, sel.category, { quiet });
      })
      .catch((e: Error) => setError(e.message));
  }

  function refreshMainView(sel: CellSelection | null): Promise<void> {
    setError(null);
    if (sel) setDetail(null);
    return recalculate()
      .then(() => getMatrix(year, bankQuery))
      .then((payload) => {
        clearDirty();
        setMatrix(payload);
        if (!sel) {
          setDetail(null);
          return;
        }
        return getTransactions(sel.person_name, sel.category, year, bankQuery).then(setDetail);
      })
      .catch((e: Error) => setError(e.message));
  }

  function applyIfDirty(sel: CellSelection | null): Promise<void> {
    if (!dirtyRef.current) return Promise.resolve();
    return refreshMainView(sel);
  }

  function loadMatrixOnly() {
    return loadDisplay(null);
  }

  useEffect(() => {
    if (!year) return;
    if (!viewInitRef.current) {
      viewInitRef.current = true;
      void loadMatrixOnly();
      return;
    }
    setSelection(null);
    setDetail(null);
    setError(null);
    void loadMatrixOnly();
  }, [year, bankView]);

  useEffect(() => {
    if (dataRev === 0) return;
    const sel = selectionRef.current;
    let cancelled = false;
    getMatrix(year, bankQuery)
      .then((payload) => {
        if (cancelled) return;
        setMatrix(payload);
        if (!sel) return;
        return getTransactions(sel.person_name, sel.category, year, bankQuery).then((next) => {
          if (!cancelled) setDetail(next);
        });
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [dataRev]);

  useEffect(() => {
    const channel = new BroadcastChannel(CHANNEL);
    channel.onmessage = (e) => {
      if (e.data === "recalculated") {
        clearDirty();
        void loadDisplay(selectionRef.current, { quiet: true });
      }
    };
    const onFocus = () => {
      void applyIfDirty(selectionRef.current);
    };
    window.addEventListener("focus", onFocus);
    return () => {
      channel.close();
      window.removeEventListener("focus", onFocus);
    };
  }, []);

  function selectCell(person_name: string, category: string) {
    if (matrix && isMatrixFooter(matrix, category)) return;
    const sel = { person_name, category };
    setSelection(sel);
    setError(null);
    if (dirtyRef.current) {
      void refreshMainView(sel);
      return;
    }
    void loadDetail(person_name, category);
  }

  function backToMatrix() {
    setSelection(null);
    setDetail(null);
    setError(null);
  }

  function modifyTransaction(modified: Transaction) {
    if (!selection) return;
    const id = String(modified.id ?? "");
    const currentCode = categoryCodeFromName(selection.category);
    const nextCode = Number(modified.category);
    setDetail((prev) => {
      if (!prev) return prev;
      const existing = prev.transactions.find((row) => String(row.id) === id);
      const categoryChanged =
        existing != null && Number(existing.category) !== nextCode;
      const descriptionChanged =
        existing != null &&
        String(existing.description ?? "") !== String(modified.description ?? "");
      if (categoryChanged && currentCode != null && nextCode !== currentCode) {
        return patchDetail(prev, { removeId: id });
      }
      if (descriptionChanged) {
        return patchDetail(prev, { update: modified, blueId: id });
      }
      if (categoryChanged) {
        return patchDetail(prev, { update: modified, boldId: id });
      }
      return prev;
    });
    recordModification(selection.person_name, modified)
      .then((res) => {
        if (res.matrix) setMatrix(res.matrix);
      })
      .catch((e: Error) => setError(e.message));
  }

  function openTermMenu(e: MouseEvent, cellText: string, transactionId: string) {
    e.preventDefault();
    e.stopPropagation();
    setError(null);
    const word = wordAtClick(e.currentTarget, e.clientX, e.clientY) || cellText.trim();
    if (!word) return;
    getSettings()
      .then((settings) => {
        setTermMenuSettings(settings);
        setTermMenu({ term: word, x: e.clientX, y: e.clientY, transactionId });
      })
      .catch((err: Error) => setError(err.message));
  }

  function closeTermMenu() {
    setTermMenu(null);
    setTermMenuSettings(null);
  }

  function saveTermMenu(term: string, targetCategory: string, general: boolean) {
    const person_name = selectionRef.current?.person_name;
    if (!general && !person_name) return Promise.resolve();
    const sel = selectionRef.current;
    const rowId = termMenu?.transactionId;
    closeTermMenu();
    if (sel && rowId && targetCategory !== sel.category) {
      setDetail((prev) => (prev ? patchDetail(prev, { removeId: rowId }) : prev));
    }
    return addCategoryTerm({
      category_name: targetCategory,
      term,
      general,
      person: general ? undefined : person_name,
    })
      .then((res) => {
        setMatrix(res.matrix);
        if (sel) return loadDetail(sel.person_name, sel.category, { quiet: true });
      })
      .catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!isPlainAlt(e)) return;
      const key = e.key.toLowerCase();
      if (key === "t") {
        e.preventDefault();
        openView("terms");
      } else if (key === "c") {
        e.preventDefault();
        openView("categories");
      } else if (key === "m") {
        e.preventDefault();
        window.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function doRefresh() {
    if (refreshing) return;
    beginRefreshBusy();
    flushSync(() => {
      setRefreshing(true);
      setError(null);
      setRefreshStatus(null);
      setConsentReady({});
    });
    clearStoredRefreshStatus(refreshScope);
    afterPaint(() => {
      refreshAll()
        .then((res) => {
          setMatrix(res.matrix);
          const payload: StoredRefreshStatus = {
            results: res.results || [],
            warnings: res.warnings || [],
          };
          const authorizationUrl = payload.results.find(
            (result) =>
              result.skipped &&
              result.reason === "needs_consent_renewal" &&
              result.authorization_url
          )?.authorization_url;
          if (authorizationUrl) {
            const authorizationWindow = window.open(
              authorizationUrl,
              "_blank",
              "noopener,noreferrer"
            );
            if (!authorizationWindow) window.location.assign(authorizationUrl);
          }
          saveStoredRefreshStatus(payload, refreshScope);
          setRefreshStatus(payload);
          setSelection(null);
          setDetail(null);
        })
        .catch((e: Error) => setError(e.message))
        .finally(() => {
          setRefreshing(false);
          endRefreshBusy();
        });
    });
  }

  function doFirstDownload(person_name: string) {
    if (refreshing || firstDownloading) return;
    beginRefreshBusy();
    flushSync(() => {
      setFirstDownloading(true);
      setError(null);
    });
    afterPaint(() => {
      const start = `${new Date().getFullYear()}-01-01`;
      const end = isoDate(new Date());
      refreshPerson(person_name, { date_from: start, date_to: end, new_year: true })
        .then((res) => {
          setMatrix(res.matrix);
          const nextResult = (res.results || [])[0];
          const prev = refreshStatus || { results: [], warnings: [] };
          const results = nextResult
            ? [
                ...prev.results.filter((r) => r.person_name !== person_name),
                nextResult,
              ]
            : prev.results.filter((r) => r.person_name !== person_name);
          const warnings = [
            ...prev.warnings.filter(
              (w) => !w.startsWith(`${person_name}:`) && !w.startsWith(`${person_name} (`)
            ),
            ...(res.warnings || []),
          ];
          const payload: StoredRefreshStatus = { results, warnings };
          saveStoredRefreshStatus(payload, refreshScope);
          setRefreshStatus(payload);
          setConsentReady({});
          setSelection(null);
          setDetail(null);
        })
        .catch((e: Error) => setError(e.message))
        .finally(() => {
          setFirstDownloading(false);
          endRefreshBusy();
        });
    });
  }

  const awaitingPostConsentFetch = (refreshStatus?.results || []).some(
    (r) =>
      r.skipped &&
      r.reason === "needs_consent_renewal" &&
      Boolean(consentReady[r.person_name])
  );

  const postConsentFiredRef = useRef<string[]>([]);
  useEffect(() => {
    if (!awaitingPostConsentFetch) return;
    const person_name = (banks?.person || "").trim();
    if (!person_name) return;
    if (postConsentFiredRef.current.includes(person_name)) return;
    let cancelled = false;
    let tries = 0;
    function attempt() {
      if (cancelled) return;
      if (hasSecrets) {
        postConsentFiredRef.current.push(person_name);
        doFirstDownload(person_name);
        return;
      }
      tries += 1;
      if (tries < 10 && !cancelled) window.setTimeout(attempt, 300);
    }
    attempt();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [awaitingPostConsentFetch, banks?.person, hasSecrets]);

  const setHeaderActions = useContext(HeaderActionsContext);
  useEffect(() => {
    const items: HeaderAction[] = [];
    if (hasSecrets && !awaitingPostConsentFetch) {
      items.push({
        id: "refresh",
        label: refreshing ? "Downloading…" : "Download transactions",
        disabled: refreshing,
        onClick: doRefresh,
      });
    }
    if (canAddPerson && addPersonUrl) {
      items.push({
        id: "add-person",
        label: "Add person",
        onClick: () => window.location.assign(addPersonUrl),
      });
    }
    setHeaderActions(items);
    return () => setHeaderActions([]);
  }, [
    hasSecrets,
    awaitingPostConsentFetch,
    refreshing,
    canAddPerson,
    addPersonUrl,
    setHeaderActions,
  ]);

  const inPView = selection !== null;

  const bankAuthUrl = (() => {
    if (!bankAuthRequired) return "";
    const person_name = banks?.person || "";
    for (const r of refreshStatus?.results || []) {
      if (
        r.person_name === person_name &&
        r.skipped &&
        r.reason === "needs_consent_renewal" &&
        r.authorization_url
      ) {
        return r.authorization_url;
      }
    }
    return "";
  })();

  const authOpenedRef = useRef<string>("");
  useEffect(() => {
    if (!bankAuthUrl) return;
    if (bankAuthUrl === authOpenedRef.current) return;
    authOpenedRef.current = bankAuthUrl;
    window.open(bankAuthUrl, "_blank", "noopener,noreferrer");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bankAuthUrl]);

  return (
    <div className="app">
      <aside className="sidebar">
        {brandName ? <FitSidebarTitle text={brandName} /> : null}

        {inPView && matrix && (
          <>
            <div className="winbar">
              <div className="sidebar-field">
                <span className="sidebar-field-legend" aria-hidden="true">
                  {"\u00a0"}
                </span>
                <button type="button" className="sidebar-knob" onClick={backToMatrix}>
                  ← Matrix
                </button>
              </div>
            </div>
            <PersonColumnTable
              matrix={matrix}
              person_name={selection.person_name}
              selectedCategory={selection.category}
              onPick={(category) => selectCell(selection.person_name, category)}
            />
          </>
        )}
      </aside>

      <main className="content">
        {error && <p className="error">{error}</p>}
        {!inPView && !matrix && !error && <p>Loading…</p>}
        {!inPView && matrix && (
          <MatrixTable matrix={matrix} selection={selection} onPick={selectCell} />
        )}
        {inPView && !detail && !error && <p>Loading…</p>}
        {inPView && detail && (
          <PTable
            categoryName={selection.category}
            detail={detail}
            year={year}
            bank={bankQuery}
            onModify={modifyTransaction}
            onCategoryError={setError}
            onTermContextMenu={openTermMenu}
          />
        )}
        {termMenu && termMenuSettings && (
          <TermContextMenu
            settings={termMenuSettings}
            initialTerm={termMenu.term}
            x={termMenu.x}
            y={termMenu.y}
            onClose={closeTermMenu}
            onPickCategory={saveTermMenu}
          />
        )}
      </main>
    </div>
  );
}

function TermsApp() {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const channelRef = useRef<BroadcastChannel | null>(null);

  useEffect(() => {
    let cancelled = false;
    function load() {
      getSettings()
        .then((data) => {
          if (!cancelled) setSettings(data);
        })
        .catch((e: Error) => {
          if (!cancelled) setError(e.message);
        });
    }
    load();
    function onShow() {
      if (document.visibilityState === "visible") load();
    }
    window.addEventListener("focus", load);
    document.addEventListener("visibilitychange", onShow);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", load);
      document.removeEventListener("visibilitychange", onShow);
    };
  }, []);

  useEffect(() => {
    const channel = new BroadcastChannel(CHANNEL);
    channelRef.current = channel;
    return () => {
      channelRef.current = null;
      channel.close();
    };
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!isPlainAlt(e)) return;
      const key = e.key.toLowerCase();
      if (key === "m") {
        e.preventDefault();
        openView("main");
      } else if (key === "t") {
        e.preventDefault();
        window.focus();
      } else if (key === "c") {
        e.preventDefault();
        openView("categories");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function updateTerms(group: string, category: string, terms: string[]) {
    setSettings((prev) => {
      if (!prev) return prev;
      if (group === "general") {
        return { ...prev, general: { ...prev.general, [category]: terms } };
      }
      const personGroup = { ...(prev.personal[group] ?? {}) };
      if (terms.length) personGroup[category] = terms;
      else delete personGroup[category];
      return { ...prev, personal: { ...prev.personal, [group]: personGroup } };
    });
    updateSettings(group, category, terms)
      .then((res) => {
        setSettings((prev) => {
          if (!prev) return prev;
          const nextTerms = res.terms ?? terms;
          if (group === "general") {
            return { ...prev, general: { ...prev.general, [category]: nextTerms } };
          }
          const personGroup = { ...(prev.personal[group] ?? {}) };
          if (nextTerms.length) personGroup[category] = nextTerms;
          else delete personGroup[category];
          return { ...prev, personal: { ...prev.personal, [group]: personGroup } };
        });
        channelRef.current?.postMessage("recalculated");
      })
      .catch((e: Error) => setError(e.message));
  }

  return (
    <div className="app terms-app">
      <aside className="sidebar">
        <div className="winbar">
          <div className="sidebar-field">
            <span className="sidebar-field-legend" aria-hidden="true">
              {"\u00a0"}
            </span>
            <button type="button" className="sidebar-knob" onClick={() => openView("main")}>
              Matrix (Alt+M)
            </button>
          </div>
        </div>
        <p className="win-hint">
          Term Window. Return to overview using <kbd>Ctrl</kbd>+<kbd>Tab</kbd> or{" "}
          <kbd>Alt</kbd>+<kbd>M</kbd>. Edits save immediately; matching bookings
          update in the background.{" "}
          {settings ? formatTermMatchHint(settings.typerules) : ""}
        </p>
      </aside>
      <main className="content terms-content">
        {error && <p className="error">{error}</p>}
        {settings ? (
          <TermsTables settings={settings} onUpdate={updateTerms} />
        ) : (
          <p>Loading…</p>
        )}
      </main>
    </div>
  );
}

type CatalogDraft = {
  key: string;
  category_id: number | null;
  local_code: string;
  label: string;
  is_remainder: boolean;
};

function reviewSubmissionMessage(raw: string): string {
  let text = String(raw || "").trim();
  for (let i = 0; i < 8; i++) {
    const jsonStart = text.indexOf("{");
    if (jsonStart >= 0) {
      try {
        const parsed = JSON.parse(text.slice(jsonStart)) as { detail?: unknown };
        if (typeof parsed.detail === "string" && parsed.detail.trim()) {
          text = parsed.detail.trim();
          continue;
        }
      } catch {
        /* keep text */
      }
    }
    const hub = text.match(/^hub \d+:\s*(.*)$/i);
    if (hub) {
      text = hub[1].trim();
      continue;
    }
    text = text.replace(/^\d{3}\s+[A-Za-z ]+:\s*/, "").trim();
    break;
  }
  return `Please review your submission: ${text || raw}`;
}

function catalogToDraft(rows: CatalogCategory[]): CatalogDraft[] {
  return rows.map((row, index) => ({
    key: row.category_id != null ? `id-${row.category_id}` : `new-${index}`,
    category_id: row.category_id ?? null,
    local_code: String(row.local_code).padStart(4, "0"),
    label: String(row.label ?? "").trim(),
    is_remainder: Boolean(row.is_remainder),
  }));
}

function CategoriesApp() {
  const [draft, setDraft] = useState<CatalogDraft[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [country, setCountry] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const channelRef = useRef<BroadcastChannel | null>(null);
  const nextKey = useRef(1);

  useEffect(() => {
    let cancelled = false;
    getCatalog()
      .then((data) => {
        if (cancelled) return;
        setCountry(data.country || "");
        setDraft(catalogToDraft(data.categories || []));
        setLoaded(true);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const channel = new BroadcastChannel(CHANNEL);
    channelRef.current = channel;
    return () => {
      channelRef.current = null;
      channel.close();
    };
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!isPlainAlt(e)) return;
      const key = e.key.toLowerCase();
      if (key === "m") {
        e.preventDefault();
        openView("main");
      } else if (key === "t") {
        e.preventDefault();
        openView("terms");
      } else if (key === "c") {
        e.preventDefault();
        window.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function patchRow(key: string, patch: Partial<CatalogDraft>) {
    setSaved(false);
    setDraft((rows) =>
      rows.map((row) => {
        if (row.key !== key) {
          if (patch.is_remainder) return { ...row, is_remainder: false };
          return row;
        }
        return { ...row, ...patch };
      })
    );
  }

  function addRow() {
    setSaved(false);
    const key = `new-${nextKey.current++}`;
    const maxCode = 9999;
    setDraft((rows) => {
      const used = new Set(
        rows.map((row) => Number.parseInt(row.local_code, 10)).filter((n) => n >= 1)
      );
      let code = 1;
      while (used.has(code) && code <= maxCode) code += 1;
      return [
        ...rows,
        {
          key,
          category_id: null,
          local_code: String(code).padStart(4, "0"),
          label: "",
          is_remainder: rows.length === 0,
        },
      ];
    });
  }

  function removeRow(key: string) {
    setSaved(false);
    setDraft((rows) => {
      const next = rows.filter((row) => row.key !== key);
      if (next.length && !next.some((row) => row.is_remainder)) {
        next[0] = { ...next[0], is_remainder: true };
      }
      return next;
    });
  }

  function save() {
    setError(null);
    setBusy(true);
    setSaved(false);
    const payload: CatalogCategory[] = draft.map((row) => ({
      category_id: row.category_id,
      local_code: Number.parseInt(row.local_code, 10),
      label: row.label.trim(),
      is_remainder: row.is_remainder,
    }));
    saveCatalog(payload)
      .then((data) => {
        setCountry(data.country || country);
        setDraft(catalogToDraft(data.categories || []));
        setSaved(true);
        channelRef.current?.postMessage("recalculated");
      })
      .catch((e: Error) => setError(reviewSubmissionMessage(e.message)))
      .finally(() => setBusy(false));
  }

  return (
    <div className="app terms-app">
      <aside className="sidebar">
        <div className="winbar">
          <div className="sidebar-field">
            <span className="sidebar-field-legend" aria-hidden="true">
              {"\u00a0"}
            </span>
            <button type="button" className="sidebar-knob" onClick={() => openView("main")}>
              Matrix (Alt+M)
            </button>
          </div>
        </div>
        <p className="win-hint">
          Category window for {country || "this country"}. Changing a name keeps
          existing bookings on that category. Deleting a category moves leftover
          bookings to unclassified.
        </p>
        <div className="sidebar-field">
          <span className="sidebar-field-legend" aria-hidden="true">
            {"\u00a0"}
          </span>
          <button type="button" className="sidebar-knob" onClick={addRow}>
            Add category
          </button>
        </div>
        <div className="sidebar-field">
          <span className="sidebar-field-legend" aria-hidden="true">
            {"\u00a0"}
          </span>
          <button
            type="button"
            className="sidebar-knob"
            disabled={busy || draft.length === 0}
            onClick={save}
          >
            {busy ? "Submitting…" : "Submit"}
          </button>
        </div>
      </aside>
      <main className="content terms-content">
        {error && <p className="error">{error}</p>}
        {saved && <p className="ok">Saved.</p>}
        {loaded ? (
          <div className="terms-scroll">
            <table className="s-table catalog-table">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Label</th>
                  <th>Unclassified</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {draft.map((row) => (
                  <tr key={row.key}>
                    <td>
                      <input
                        className="catalog-code"
                        inputMode="numeric"
                        maxLength={4}
                        value={row.local_code}
                        onChange={(e) => patchRow(row.key, { local_code: e.target.value })}
                      />
                    </td>
                    <td>
                      <input
                        className="catalog-label"
                        value={row.label}
                        onChange={(e) => patchRow(row.key, { label: e.target.value })}
                      />
                    </td>
                    <td>
                      <input
                        type="radio"
                        name="catalog-remainder"
                        checked={row.is_remainder}
                        onChange={() => patchRow(row.key, { is_remainder: true })}
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="catalog-delete"
                        disabled={draft.length === 1}
                        onClick={() => removeRow(row.key)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>Loading…</p>
        )}
      </main>
    </div>
  );
}

function kindCaption(kind: string): string {
  if (kind === "hub") return "Hub 8200";
  if (kind === "country") return "Country";
  if (kind === "center") return "Center";
  if (kind === "person") return "Person";
  return kind || "Login";
}

function SetPasswordApp() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [mobile, setMobile] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getPersonSecurity()
      .then((row) => {
        if (!cancelled) setMobile(row.mobile_phone || "");
      })
      .catch((e: Error) => {
        if (!cancelled) setError(reviewSubmissionMessage(e.message));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!isPlainAlt(e)) return;
      if (e.key.toLowerCase() === "m") {
        e.preventDefault();
        openView("main");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(null);
    setBusy(true);
    setPersonPassword({
      current,
      new_password: next,
      confirm,
      mobile_phone: mobile.trim(),
    })
      .then(() => {
        setOk("Password saved.");
        setCurrent("");
        setNext("");
        setConfirm("");
      })
      .catch((err: Error) => setError(reviewSubmissionMessage(err.message)))
      .finally(() => setBusy(false));
  }

  return (
    <div className="app terms-app">
      <aside className="sidebar">
        <div className="winbar">
          <div className="sidebar-field">
            <span className="sidebar-field-legend" aria-hidden="true">
              {"\u00a0"}
            </span>
            <button type="button" className="sidebar-knob" onClick={() => openView("main")}>
              Matrix (Alt+M)
            </button>
          </div>
        </div>
        <p className="win-hint">
          Mobile phone number activates two-step login by sending a 6-digit code via SMS
        </p>
      </aside>
      <main className="terms-main password-main">
        <form onSubmit={submit} className="login-card password-card">
          <h1 className="password-title">Set password</h1>
          <label className="login-label">
            Current password
            <input
              className="login-input"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              disabled={busy}
              required
            />
          </label>
          <label className="login-label">
            New password
            <input
              className="login-input"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              disabled={busy}
              required
            />
          </label>
          <label className="login-label">
            Confirm new password
            <input
              className="login-input"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={busy}
              required
            />
          </label>
          <label className="login-label">
            Mobile phone (optional)
            <input
              className="login-input"
              type="tel"
              placeholder="+31612345678"
              value={mobile}
              onChange={(e) => setMobile(e.target.value)}
              disabled={busy}
            />
          </label>
          {error ? <p className="login-error">{error}</p> : null}
          {ok ? <p className="ok">{ok}</p> : null}
          <div className="password-actions">
            <button
              className="password-knob password-knob-cancel"
              type="button"
              disabled={busy}
              onClick={() => openView("main")}
            >
              Cancel
            </button>
            <button className="password-knob password-knob-save" type="submit" disabled={busy}>
              {busy ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}

function IpAccessApp() {
  const [data, setData] = useState<IpAccessResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ip, setIp] = useState("");
  const [target, setTarget] = useState("");

  function apply(next: IpAccessResponse) {
    setData(next);
    setTarget((prev) => {
      if (prev && next.targets.some((item) => item.target === prev)) return prev;
      return next.targets[0]?.target || "";
    });
  }

  useEffect(() => {
    let cancelled = false;
    getIpAccess()
      .then((payload) => {
        if (!cancelled) apply(payload);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!isPlainAlt(e)) return;
      if (e.key.toLowerCase() === "m") {
        e.preventDefault();
        openView("main");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function add() {
    setError(null);
    setBusy(true);
    addIpAccess({ ip: ip.trim(), target })
      .then((payload) => {
        apply(payload);
        setIp("");
      })
      .catch((e: Error) => setError(reviewSubmissionMessage(e.message)))
      .finally(() => setBusy(false));
  }

  function remove(rowIp: string, rowTarget: string) {
    setError(null);
    setBusy(true);
    deleteIpAccess(rowIp, rowTarget)
      .then(apply)
      .catch((e: Error) => setError(reviewSubmissionMessage(e.message)))
      .finally(() => setBusy(false));
  }

  const targets: IpAccessTarget[] = data?.targets || [];

  return (
    <div className="app terms-app">
      <aside className="sidebar">
        <div className="winbar">
          <div className="sidebar-field">
            <span className="sidebar-field-legend" aria-hidden="true">
              {"\u00a0"}
            </span>
            <button type="button" className="sidebar-knob" onClick={() => openView("main")}>
              Matrix (Alt+M)
            </button>
          </div>
        </div>
        <p className="win-hint">
          Allowed client IPs for country and center logins (stored as a
          comma-separated list on egress_ip). Empty list means that login is
          not IP-restricted. Person logins are not IP-gated.
        </p>
        <div className="sidebar-field">
          <span className="sidebar-field-legend">Login</span>
          <select
            className="ip-target"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            disabled={targets.length === 0}
          >
            {targets.map((item) => (
              <option key={item.target} value={item.target}>
                {kindCaption(item.kind)} — {item.label}
                {item.username ? ` (${item.username})` : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="sidebar-field">
          <span className="sidebar-field-legend">IP</span>
          <input
            className="ip-address"
            value={ip}
            placeholder="1.2.3.4"
            onChange={(e) => setIp(e.target.value)}
          />
        </div>
        <div className="sidebar-field">
          <span className="sidebar-field-legend" aria-hidden="true">
            {"\u00a0"}
          </span>
          <button
            type="button"
            className="sidebar-knob"
            disabled={busy || !target || !ip.trim()}
            onClick={add}
          >
            {busy ? "Saving…" : "Add IP"}
          </button>
        </div>
      </aside>
      <main className="content terms-content">
        {error && <p className="error">{error}</p>}
        {data ? (
          <div className="terms-scroll">
            <table className="s-table catalog-table">
              <thead>
                <tr>
                  <th>Login</th>
                  <th>Name</th>
                  <th>IP</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.rows.length === 0 ? (
                  <tr>
                    <td colSpan={4}>No IP restrictions in your scope.</td>
                  </tr>
                ) : (
                  data.rows.map((row) => (
                    <tr key={`${row.target}:${row.ip}`}>
                      <td>{kindCaption(row.kind)}</td>
                      <td>
                        {row.label}
                        {row.username ? ` (${row.username})` : ""}
                      </td>
                      <td>{row.ip}</td>
                      <td>
                        <button
                          type="button"
                          className="catalog-delete"
                          disabled={busy}
                          onClick={() => remove(row.ip, row.target)}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        ) : (
          <p>Loading…</p>
        )}
      </main>
    </div>
  );
}

function MatrixTable({
  matrix,
  selection,
  onPick,
}: {
  matrix: MatrixResponse;
  selection: CellSelection | null;
  onPick: (person_name: string, category: string) => void;
}) {
  const { categories, people, cells } = matrix;
  const terms = matrix.table_header_terms;
  return (
    <table className="totals-table matrix-table">
      <thead>
        <tr>
          <th className="cat">{tableHeaderTerm(terms, "Category")}</th>
          {people.map((p) => (
            <th key={p.person_name} className="num">
              {p.person_name}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {categories.map((cat) => (
          <tr
            key={cat}
            className={`${selection?.category === cat ? "active" : ""}${isMatrixFooter(matrix, cat) ? " banksaldo-row" : ""}`}
          >
            <td className="cat">{displayCategoryName(cat)}</td>
            {people.map((p) => {
              const amount = cells[cat]?.[p.person_name] ?? "";
              const isActive =
                selection?.person_name === p.person_name && selection?.category === cat;
              const clickable = !isMatrixFooter(matrix, cat) && amount !== "";
              return (
                <td
                  key={p.person_name}
                  className={`num${clickable ? " clickable" : ""}${isActive ? " active-cell" : ""}`}
                  onClick={clickable ? () => onPick(p.person_name, cat) : undefined}
                >
                  {displayMatrixCell(matrix, cat, amount)}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PersonColumnTable({
  matrix,
  person_name,
  selectedCategory,
  onPick,
}: {
  matrix: MatrixResponse;
  person_name: string;
  selectedCategory: string | null;
  onPick: (category: string) => void;
}) {
  const { categories, cells } = matrix;
  const terms = matrix.table_header_terms;
  return (
    <table className="totals-table">
      <thead>
        <tr>
          <th className="cat">{tableHeaderTerm(terms, "Category")}</th>
          <th className="num">{person_name}</th>
        </tr>
      </thead>
      <tbody>
        {categories.map((cat) => (
          <tr
            key={cat}
            className={`${cat === selectedCategory ? "active" : ""}${isMatrixFooter(matrix, cat) ? " banksaldo-row" : ""}`}
          >
            <td className="cat">{displayCategoryName(cat)}</td>
            {(() => {
              const amount = cells[cat]?.[person_name] ?? "";
              const clickable = !isMatrixFooter(matrix, cat) && amount !== "";
              return (
                <td
                  className={`num${clickable ? " clickable" : ""}`}
                  onClick={clickable ? () => onPick(cat) : undefined}
                >
                  {displayMatrixCell(matrix, cat, amount)}
                </td>
              );
            })()}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function centsFromInput(text: string): number {
  const t = text.trim().replace(/\s/g, "").replace(",", ".");
  if (!t || t === "+" || t === "-" || t === "." || t === "+." || t === "-.") return 0;
  const n = Number(t);
  if (!Number.isFinite(n)) return 0;
  return Math.round(n * 100);
}

function formatCents(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  return `${sign}${(Math.abs(cents) / 100).toFixed(2)}`;
}

function formatUnity(n: number): string {
  const rounded = Math.sign(n) * Math.round(Math.abs(n));
  const sign = rounded < 0 ? "-" : "";
  const grouped = String(Math.abs(rounded)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${sign}${grouped}`;
}

function formatDisplayNumber(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") {
    return Number.isFinite(value) ? formatUnity(value) : "";
  }
  const text = String(value).trim();
  if (!text) return "";
  if (/^\d{1,2}-\d{1,2}-\d{2,4}$/.test(text)) return text;
  const normalized = text.replace(/\s/g, "").replace(",", ".");
  if (!/^[+-]?\d+(\.\d+)?$/.test(normalized)) return text;
  const n = Number(normalized);
  return Number.isFinite(n) ? formatUnity(n) : text;
}

function displayMatrixCell(matrix: MatrixResponse, category: string, raw: string): string {
  if (category === matrixFooterNames(matrix).last_booked) return raw;
  return formatDisplayNumber(raw);
}

function closeSplitPage() {
  openView("main");
}

function SplitApp() {
  const params = new URLSearchParams(window.location.search);
  const person = params.get("person") || "";
  const sourceId = params.get("id") || "";
  const year = params.get("year") || undefined;
  const bank = params.get("bank") || undefined;

  const [originalCents, setOriginalCents] = useState(0);
  const [parentDesc, setParentDesc] = useState("");
  const [heading, setHeading] = useState("");
  const [lines, setLines] = useState<{ key: string; id: string | null; description: string; amountText: string }[]>(
    []
  );
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const channelRef = useRef<BroadcastChannel | null>(null);
  const nextKey = useRef(1);

  useEffect(() => {
    let cancelled = false;
    if (!person || !sourceId) {
      setError("Missing person or transaction.");
      return;
    }
    getTransactionSplit(person, sourceId, year, bank)
      .then((data) => {
        if (cancelled) return;
        setOriginalCents(centsFromInput(data.original_amount));
        setParentDesc(data.description || "");
        const who = [data.name, data.date].filter(Boolean).join(" · ");
        setHeading(who);
        setLines(
          (data.lines || []).map((line, index) => ({
            key: line.id ? `id-${line.id}` : `line-${index}`,
            id: line.id || null,
            description: line.description || "",
            amountText: line.amount || "0.00",
          }))
        );
        setLoaded(true);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [person, sourceId, year, bank]);

  useEffect(() => {
    const channel = new BroadcastChannel(CHANNEL);
    channelRef.current = channel;
    return () => {
      channelRef.current = null;
      channel.close();
    };
  }, []);

  const lineCents = lines.reduce((sum, line) => sum + centsFromInput(line.amountText), 0);
  const parentCents = originalCents - lineCents;
  const parentAmount = formatDisplayNumber(parentCents / 100);

  function addLine() {
    const key = `new-${nextKey.current}`;
    nextKey.current += 1;
    setLines((rows) => [...rows, { key, id: null, description: "", amountText: "0.00" }]);
  }

  function save() {
    setError(null);
    setBusy(true);
    saveTransactionSplit(person, {
      id: sourceId,
      description: parentDesc,
      lines: lines.map((line) => ({
        id: line.id,
        description: line.description,
        amount: formatCents(centsFromInput(line.amountText)),
      })),
      year,
      bank,
    })
      .then(() => {
        channelRef.current?.postMessage("recalculated");
        closeSplitPage();
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  }

  return (
    <div className="app terms-app">
      <aside className="sidebar">
        <div className="winbar">
          <div className="sidebar-field">
            <span className="sidebar-field-legend" aria-hidden="true">
              {"\u00a0"}
            </span>
            <button type="button" className="sidebar-knob" onClick={() => openView("main")}>
              Matrix (Alt+M)
            </button>
          </div>
        </div>
        <p className="win-hint">
          Split this booking into extra lines. The original amount is the remainder,
          so the total always stays {formatDisplayNumber(originalCents / 100)}.
        </p>
        <div className="sidebar-field">
          <span className="sidebar-field-legend" aria-hidden="true">
            {"\u00a0"}
          </span>
          <button type="button" className="sidebar-knob" onClick={addLine} disabled={!loaded}>
            Add line
          </button>
        </div>
        <div className="sidebar-field">
          <span className="sidebar-field-legend" aria-hidden="true">
            {"\u00a0"}
          </span>
          <button type="button" className="sidebar-knob" disabled={busy || !loaded} onClick={save}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </aside>
      <main className="content terms-content">
        {error && <p className="error">{error}</p>}
        {loaded ? (
          <div className="terms-scroll">
            {heading ? <p className="win-hint">{person} · {heading}</p> : null}
            <table className="s-table catalog-table">
              <thead>
                <tr>
                  <th>Amount</th>
                  <th>Description</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className={parentAmount.trim().startsWith("-") ? "amount num neg" : "amount num"}>
                    {parentAmount}
                  </td>
                  <td>
                    <input
                      className="catalog-label"
                      value={parentDesc}
                      onChange={(e) => setParentDesc(e.target.value)}
                    />
                  </td>
                  <td />
                </tr>
                {lines.map((line) => {
                  const negative = centsFromInput(line.amountText) < 0;
                  return (
                    <tr key={line.key}>
                      <td>
                        <input
                          className={`split-amount${negative ? " neg" : ""}`}
                          value={line.amountText}
                          onChange={(e) =>
                            setLines((rows) =>
                              rows.map((row) =>
                                row.key === line.key ? { ...row, amountText: e.target.value } : row
                              )
                            )
                          }
                        />
                      </td>
                      <td>
                        <input
                          className="catalog-label"
                          value={line.description}
                          onChange={(e) =>
                            setLines((rows) =>
                              rows.map((row) =>
                                row.key === line.key ? { ...row, description: e.target.value } : row
                              )
                            )
                          }
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="catalog-delete"
                          onClick={() => setLines((rows) => rows.filter((row) => row.key !== line.key))}
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p>Loading…</p>
        )}
      </main>
    </div>
  );
}

function PTable({
  categoryName,
  detail,
  year,
  bank,
  onModify,
  onCategoryError,
  onTermContextMenu,
}: {
  categoryName: string;
  detail: TransactionsResponse;
  year?: string;
  bank?: string;
  onModify: (transaction: Transaction) => void;
  onCategoryError?: (message: string | null) => void;
  onTermContextMenu?: (e: MouseEvent, cellText: string, transactionId: string) => void;
}) {
  const transactions = Array.isArray(detail.transactions) ? detail.transactions : [];
  const keywords = Array.isArray(detail.keywords) ? detail.keywords : [];
  const validCategoryCodes = new Set(detail.valid_category_codes ?? []);
  const descriptionModified = new Set(detail.description_modified_ids ?? []);
  const categoryModified = new Set(detail.category_modified_ids ?? []);
  const columns = categoryBeforeDescription(
    Array.isArray(detail.columns) && detail.columns.length > 0
      ? detail.columns
      : ptableColumns(transactions)
  );

  function safeHighlight(text: string): ReactNode {
    try {
      return highlight(text, keywords);
    } catch {
      return text;
    }
  }

  function openSplit(e: MouseEvent, transaction: Transaction) {
    e.preventDefault();
    e.stopPropagation();
    const id = String(transaction.id ?? "");
    if (!id) return;
    const params = new URLSearchParams();
    params.set("view", "split");
    params.set("person", detail.person);
    params.set("id", id);
    if (year) params.set("year", year);
    if (bank && bank !== "consolidated") params.set("bank", bank);
    showInThisWindow(`${window.location.pathname}?${params.toString()}`);
  }

  function renderCell(t: Transaction, column: string) {
    if (column === "amount") {
      const amount = formatDisplayNumber(t.amount);
      const negative = String(t.amount ?? "").trim().startsWith("-") || Number(t.amount) < 0;
      return (
        <td
          key={column}
          className={`${negative ? "amount num neg" : "amount num"} amount-source`}
          onContextMenu={(e) => openSplit(e, t)}
        >
          {amount}
        </td>
      );
    }
    if (column === "type") {
      return <td key={column}>{abbreviate(detail.abbreviations, t.type)}</td>;
    }
    if (column === "name") {
      const text = formatCell(t.name);
      return (
        <td
          key={column}
          className="name term-source"
          onContextMenu={
            onTermContextMenu ? (e) => onTermContextMenu(e, text, String(t.id ?? "")) : undefined
          }
        >
          {safeHighlight(text)}
        </td>
      );
    }
    if (column === "description") {
      const text = formatCell(t.description);
      return (
        <td
          key={column}
          className="desc term-source"
          onContextMenu={
            onTermContextMenu ? (e) => onTermContextMenu(e, text, String(t.id ?? "")) : undefined
          }
        >
          <EditableField
            value={text}
            display={safeHighlight(text)}
            onCommit={(v) => onModify({ ...t, description: v })}
          />
        </td>
      );
    }
    if (column === "category") {
      const catModified = categoryModified.has(String(t.id));
      return (
        <td key={column} className={`num${catModified ? " category-modified" : ""}`}>
          <EditableField
            value={formatCell(t.category)}
            onCommit={(v) => {
              const code = parseInt(v, 10);
              if (Number.isNaN(code) || !validCategoryCodes.has(code)) {
                onCategoryError?.(
                  `Unknown category code. Use one of: ${[...validCategoryCodes].sort((a, b) => a - b).join(", ")}`
                );
                return;
              }
              onModify({ ...t, category: code });
            }}
          />
        </td>
      );
    }
    return <td key={column}>{formatCell(t[column])}</td>;
  }

  return (
    <div className="p-panel">
      <div className="p-heading">
        <strong>
          {detail.person} / {displayCategoryName(categoryName)}
        </strong>
      </div>
      {transactions.length === 0 ? (
        <p>No transactions in this category</p>
      ) : (
        <table className="p-table">
          <colgroup>
            {columns.map((c) => (
              <col key={c} className={columnColClass(c)} />
            ))}
          </colgroup>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c} className={columnCellClass(c)}>
                  {columnHeaderLabel(c, detail.table_header_terms)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {transactions.map((t) => {
              const descModified = descriptionModified.has(String(t.id));
              return (
                <tr key={String(t.id)} className={descModified ? "modified" : undefined}>
                  {columns.map((c) => renderCell(t, c))}
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

function TermContextMenu({
  settings,
  initialTerm,
  x,
  y,
  onClose,
  onPickCategory,
}: {
  settings: SettingsResponse;
  initialTerm: string;
  x: number;
  y: number;
  onClose: () => void;
  onPickCategory: (
    term: string,
    targetCategory: string,
    general: boolean
  ) => void | Promise<void>;
}) {
  const [term, setTerm] = useState(initialTerm);
  const [saving, setSaving] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState({ left: x, top: y });

  const categories = settings.categories.filter(
    (name) => name !== settings.remainder_category && isBookingCategoryName(name)
  );

  useEffect(() => {
    setTerm(initialTerm);
  }, [initialTerm]);

  useEffect(() => {
    const el = menuRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const pad = 8;
    setPos({
      left: Math.min(x, window.innerWidth - rect.width - pad),
      top: Math.min(y, window.innerHeight - rect.height - pad),
    });
  }, [x, y, categories.length, initialTerm]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function pick(category: string, general: boolean) {
    const cleaned = term.trim();
    if (!cleaned || saving) return;
    setSaving(true);
    Promise.resolve(onPickCategory(cleaned, category, general)).finally(() =>
      setSaving(false)
    );
  }

  return (
    <div
      className="term-context-backdrop"
      onClick={onClose}
      onContextMenu={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <div
        ref={menuRef}
        className="term-context-menu"
        style={{ left: Math.max(8, pos.left), top: Math.max(8, pos.top) }}
        role="menu"
        onClick={(e) => e.stopPropagation()}
        onContextMenu={(e) => e.preventDefault()}
      >
        <input
          className="term-context-title"
          value={term}
          autoFocus
          spellCheck={false}
          onChange={(e) => setTerm(e.target.value)}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              onClose();
            }
          }}
        />
        <div className="term-context-table-wrap">
          <table className="term-context-table">
            <thead>
              <tr>
                <th className="term-context-cat-head">
                  {tableHeaderTerm(settings.table_header_terms, "Category")}
                </th>
                <th
                  className="term-context-gp-head"
                  title={tableHeaderTerm(settings.table_header_terms, "General")}
                >
                  {tableHeaderTerm(settings.table_header_terms, "G")}
                </th>
                <th
                  className="term-context-gp-head"
                  title={tableHeaderTerm(settings.table_header_terms, "Personal")}
                >
                  {tableHeaderTerm(settings.table_header_terms, "P")}
                </th>
              </tr>
            </thead>
            <tbody>
              {categories.map((name) => (
                <tr key={name}>
                  <td className="term-context-cat">{displayCategoryName(name)}</td>
                  <td className="term-context-gp">
                    <input
                      type="checkbox"
                      aria-label={`${name} general`}
                      disabled={saving || !term.trim()}
                      onChange={() => pick(name, true)}
                    />
                  </td>
                  <td className="term-context-gp">
                    <input
                      type="checkbox"
                      aria-label={`${name} personal`}
                      disabled={saving || !term.trim()}
                      onChange={() => pick(name, false)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button
          type="button"
          className="term-context-item term-context-cancel"
          role="menuitem"
          onClick={onClose}
          disabled={saving}
        >
          cancel
        </button>
      </div>
    </div>
  );
}

function charOffsetFromPoint(root: EventTarget & Element, clientX: number, clientY: number): number | null {
  const doc = document as Document & {
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
    caretPositionFromPoint?: (
      x: number,
      y: number
    ) => { offsetNode: Node; offset: number } | null;
  };
  let node: Node | null = null;
  let offset = 0;
  if (typeof doc.caretRangeFromPoint === "function") {
    const range = doc.caretRangeFromPoint(clientX, clientY);
    if (!range) return null;
    node = range.startContainer;
    offset = range.startOffset;
  } else if (typeof doc.caretPositionFromPoint === "function") {
    const pos = doc.caretPositionFromPoint(clientX, clientY);
    if (!pos) return null;
    node = pos.offsetNode;
    offset = pos.offset;
  } else {
    return null;
  }
  if (!root.contains(node)) return null;

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let total = 0;
  let current: Node | null;
  while ((current = walker.nextNode())) {
    if (current === node) return total + offset;
    total += (current.textContent || "").length;
  }
  return null;
}

function wordAtIndex(text: string, index: number): string {
  if (!text) return "";
  if (index < 0) index = 0;
  if (index >= text.length) index = text.length - 1;
  if (index < 0) return "";

  const isWordChar = (ch: string) => /[0-9A-Za-zÀ-ÿ_&-]/.test(ch);
  if (!isWordChar(text[index])) {
    let left = index - 1;
    while (left >= 0 && !isWordChar(text[left])) left--;
    if (left < 0) return "";
    index = left;
  }
  let start = index;
  let end = index + 1;
  while (start > 0 && isWordChar(text[start - 1])) start--;
  while (end < text.length && isWordChar(text[end])) end++;
  return text.slice(start, end);
}

function wordAtClick(root: EventTarget, clientX: number, clientY: number): string {
  if (!(root instanceof Element)) return "";
  const text = root.textContent || "";
  const offset = charOffsetFromPoint(root, clientX, clientY);
  if (offset === null) return text.trim();
  return wordAtIndex(text, offset);
}

function termsTableCategories(settings: SettingsResponse): string[] {
  return settings.categories.filter(
    (name) => name !== settings.remainder_category && isBookingCategoryName(name)
  );
}

function termsColumnWidths(
  columns: string[],
  general: Record<string, string[]>,
  personal: Record<string, Record<string, string[]>>,
  people: PersonInfo[]
): number[] {
  const measure = (text: string) => Math.max(text.length, 1);

  return columns.map((category) => {
    const texts = [category, ...(general[category] ?? []), "+ term"];
    for (const p of people) {
      texts.push(...(personal[p.person_name]?.[category] ?? []));
    }
    const maxChars = Math.max(...texts.map(measure));
    return Math.ceil(maxChars * 7.5 + 20);
  });
}

/** Stable empty list so `?? EMPTY_TERMS` does not allocate a new [] every render. */
const EMPTY_TERMS: string[] = [];

function TermsTables({
  settings,
  onUpdate,
}: {
  settings: SettingsResponse;
  onUpdate: (group: string, category: string, terms: string[]) => void;
}) {
  const { people, general, personal } = settings;
  const columns = termsTableCategories(settings);
  const columnWidths = termsColumnWidths(columns, general, personal, people);

  return (
    <div className="terms-scroll">
      <div className="terms-panels">
        <section className="terms-panel terms-panel-general" aria-label="General terms">
          <h2 className="terms-panel-label">
            {tableHeaderTerm(settings.table_header_terms, "General")}
          </h2>
          <TermsColumnTable
            columns={columns}
            columnWidths={columnWidths}
            termsForCategory={(name) => general[name] ?? EMPTY_TERMS}
            onCommit={(name, terms) => onUpdate("general", name, terms)}
          />
        </section>
        {people.map((p) => (
          <section
            key={p.person_name}
            className="terms-panel terms-panel-personal"
            aria-label={`${p.person_name} terms`}
          >
            <h2 className="terms-panel-label">{p.person_name}</h2>
            <TermsColumnTable
              columns={columns}
              columnWidths={columnWidths}
              termsForCategory={(name) => personal[p.person_name]?.[name] ?? EMPTY_TERMS}
              onCommit={(name, terms) => onUpdate(p.person_name, name, terms)}
            />
          </section>
        ))}
      </div>
    </div>
  );
}

function TermsColumnTable({
  columns,
  columnWidths,
  termsForCategory,
  onCommit,
}: {
  columns: string[];
  columnWidths: number[];
  termsForCategory: (category: string) => string[];
  onCommit: (category: string, terms: string[]) => void;
}) {
  return (
    <table className="s-table s-table-terms">
      <colgroup>
        {columns.map((name, index) => (
          <col key={name} style={{ width: `${columnWidths[index]}px` }} />
        ))}
      </colgroup>
      <thead>
        <tr>
          {columns.map((name) => (
            <th key={name} title={name}>
              {displayCategoryName(name)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        <tr>
          {columns.map((name) => (
            <td key={name}>
              <EditableCell
                terms={termsForCategory(name)}
                onCommit={(terms) => onCommit(name, terms)}
              />
            </td>
          ))}
        </tr>
      </tbody>
    </table>
  );
}

function sortTerms(values: string[]): string[] {
  return [...values].sort((a, b) => a.localeCompare(b));
}

function EditableCell({
  terms,
  onCommit,
}: {
  terms: string[];
  onCommit: (terms: string[]) => void;
}) {
  const [draft, setDraft] = useState<string[]>(() => sortTerms(terms));
  const [add, setAdd] = useState("");
  const draftRef = useRef(draft);
  draftRef.current = draft;
  // Sync from props only when content changes. A new `[]` every parent render
  // (empty categories + 1s status poll) used to clear the "+ term" field mid-typing.
  const termsKey = terms.join("\0");
  const prevTermsKey = useRef(termsKey);

  useEffect(() => {
    if (prevTermsKey.current === termsKey) return;
    prevTermsKey.current = termsKey;
    const next = sortTerms(terms);
    draftRef.current = next;
    setDraft(next);
    setAdd("");
  }, [terms, termsKey]);

  function commit(next: string[]) {
    const cleaned = sortTerms(next.map((t) => t.trim()).filter(Boolean));
    const current = sortTerms(terms.map((t) => t.trim()).filter(Boolean));
    if (!arraysEqual(cleaned, current)) onCommit(cleaned);
  }

  function removeAt(index: number) {
    commit(draftRef.current.filter((_, idx) => idx !== index));
  }

  function commitAdd() {
    const t = add.trim();
    if (!t) return;
    commit([...draftRef.current, t]);
    setAdd("");
  }

  return (
    <div className="terms">
      {draft.map((term, i) => (
        <div key={i} className="term-row">
          <input
            className="term-input"
            value={term}
            onChange={(e) => {
              const value = e.target.value;
              setDraft((d) => {
                const next = d.map((t, idx) => (idx === i ? value : t));
                draftRef.current = next;
                return next;
              });
            }}
            onBlur={() => commit(draftRef.current)}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
            }}
          />
          <button
            type="button"
            className="term-delete"
            title="Delete term"
            onClick={() => removeAt(i)}
          >
            ×
          </button>
        </div>
      ))}
      <input
        className="term-input add"
        value={add}
        placeholder="+ term"
        onChange={(e) => setAdd(e.target.value)}
        onBlur={commitAdd}
        onKeyDown={(e) => {
          if (e.key === "Enter") commitAdd();
        }}
      />
    </div>
  );
}

function columnColClass(column: string): string {
  return column === "description" ? "desc-col" : `col-${column}`;
}

function columnCellClass(column: string): string | undefined {
  if (column === "description") return "desc";
  return undefined;
}

function categoryBeforeDescription(columns: string[]): string[] {
  const rest = columns.filter((key) => key !== "category" && key !== "description");
  if (columns.includes("category")) rest.push("category");
  if (columns.includes("description")) rest.push("description");
  return rest;
}

function ptableColumns(transactions: Transaction[]): string[] {
  const hidden = new Set(["id", "currency", "modification", "hit"]);
  const columns: string[] = [];
  for (const t of transactions) {
    for (const key of Object.keys(t)) {
      if (!hidden.has(key) && !columns.includes(key)) {
        columns.push(key);
      }
    }
  }
  return categoryBeforeDescription(columns);
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function EditableField({
  value,
  display,
  multiline,
  onCommit,
}: {
  value: string;
  display?: ReactNode;
  multiline?: boolean;
  onCommit: (value: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  if (!editing) {
    return (
      <span className="editable" onClick={() => setEditing(true)}>
        {display ?? value}
      </span>
    );
  }

  function commit() {
    setEditing(false);
    if (draft !== value) onCommit(draft);
  }

  if (multiline) {
    return (
      <textarea
        className="cell-edit"
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
      />
    );
  }

  return (
    <input
      className="cell-edit"
      autoFocus
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
      }}
    />
  );
}

function arraysEqual(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function lettersOnly(word: string): string {
  return word.replace(/[^a-z.]/gi, "").toLowerCase();
}

function termToPattern(term: string): string {
  let pattern = "";
  let lastWildcard = false;
  for (const ch of term) {
    if (ch === "#") {
      if (!lastWildcard) {
        pattern += "[a-z.]*";
        lastWildcard = true;
      }
    } else {
      pattern += escapeRegExp(ch);
      lastWildcard = false;
    }
  }
  return pattern;
}

function matchesHashWord(term: string, word: string): boolean {
  const pattern = new RegExp(`^${termToPattern(term)}$`, "i");
  const candidates = new Set<string>([word.toLowerCase(), lettersOnly(word)]);
  for (const candidate of candidates) {
    if (candidate && pattern.test(candidate)) return true;
  }
  return false;
}

function highlightWithRegex(text: string, terms: string[]): ReactNode {
  if (terms.length === 0) return text;
  const pattern = terms
    .sort((a, b) => b.length - a.length)
    .map((t) => (t.includes("#") ? termToPattern(t) : escapeRegExp(t)))
    .join("|");
  const re = new RegExp(`\\b(?:${pattern})\\b`, "gi");
  const nodes: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(re)) {
    const start = match.index ?? 0;
    const end = start + match[0].length;
    if (start > last) nodes.push(text.slice(last, start));
    nodes.push(<strong key={start}>{match[0]}</strong>);
    last = end;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes.length === 1 ? nodes[0] : <>{nodes}</>;
}

function highlightRanges(text: string, ranges: Array<[number, number]>): ReactNode {
  if (ranges.length === 0) return text;
  const merged: Array<[number, number]> = [];
  for (const [start, end] of ranges.sort((a, b) => a[0] - b[0])) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1]) {
      last[1] = Math.max(last[1], end);
    } else {
      merged.push([start, end]);
    }
  }
  const nodes: ReactNode[] = [];
  let last = 0;
  for (const [start, end] of merged) {
    if (start > last) nodes.push(text.slice(last, start));
    nodes.push(<strong key={start}>{text.slice(start, end)}</strong>);
    last = end;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes.length === 1 ? nodes[0] : <>{nodes}</>;
}

function atomicHighlightTerms(keywords: string[]): string[] {
  const atoms = new Set<string>();
  for (const keyword of keywords) {
    const term = keyword.trim().toLowerCase();
    if (!term) continue;
    const andParts = term.includes(" && ") ? term.split(" && ") : [term];
    for (const part of andParts) {
      const cleaned = part.trim();
      if (cleaned) atoms.add(cleaned);
    }
  }
  return [...atoms];
}

function highlight(text: string, keywords: string[]): ReactNode {
  const terms = atomicHighlightTerms(keywords);
  if (terms.length === 0) return text;

  const hashWordTerms = terms.filter((t) => t.includes("#") && !t.includes(" "));
  const plainTerms = terms.filter((t) => !t.includes("#"));

  if (hashWordTerms.length === 0) {
    return highlightWithRegex(text, plainTerms);
  }

  const ranges: Array<[number, number]> = [];

  if (plainTerms.length > 0) {
    const pattern = plainTerms
      .sort((a, b) => b.length - a.length)
      .map(escapeRegExp)
      .join("|");
    const re = new RegExp(`\\b(?:${pattern})\\b`, "gi");
    for (const match of text.matchAll(re)) {
      const start = match.index ?? 0;
      ranges.push([start, start + match[0].length]);
    }
  }

  if (hashWordTerms.length > 0) {
    for (const match of text.matchAll(/\S+/g)) {
      const word = match[0];
      const start = match.index ?? 0;
      if (hashWordTerms.some((term) => matchesHashWord(term, word))) {
        ranges.push([start, start + word.length]);
      }
    }
  }

  if (ranges.length === 0) return text;
  return highlightRanges(text, ranges);
}
