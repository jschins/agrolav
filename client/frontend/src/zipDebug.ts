/**
 * ZIP_DEBUG
 * Temporary Export-zip trace from the boekhouding window.
 * When the zip works, delete this file and every ZIP_DEBUG mark in App.tsx.
 */

function textOf(error: unknown): string {
  if (error instanceof Error) {
    return `${error.name}: ${error.message}${error.stack ? `\n${error.stack}` : ""}`;
  }
  return String(error);
}

export function zipReply(source: MessageEventSource | null, payload: unknown): string {
  try {
    if (!source) return "reply skipped, source is null";
    (source as Window).postMessage(payload, "*");
    return "reply posted";
  } catch (error) {
    return `reply threw ${textOf(error)}`;
  }
}

export function zipReceivedDetail(event: MessageEvent, activeYear: string): string {
  let source = "source=null";
  try {
    source = event.source ? "source=set" : "source=null";
  } catch (error) {
    source = `source threw ${textOf(error)}`;
  }
  const data = event.data;
  const keys =
    data && typeof data === "object" ? Object.keys(data as object).join(",") : typeof data;
  return [
    "client received",
    `activeYear=${activeYear || "(empty)"}`,
    `origin=${event.origin || "(empty)"}`,
    source,
    `dataKeys=${keys}`,
    `clientHref=${location.href}`,
    `clientOrigin=${location.origin}`,
    `ua=${navigator.userAgent}`,
    `visibility=${document.visibilityState}`,
    `online=${String(navigator.onLine)}`,
    `now=${Date.now()}`,
  ].join(" ");
}

export function zipFailDetail(current: string, elapsed: string, error: unknown): string {
  return `during ${current} after ${elapsed}: ${textOf(error)}`;
}

export function zipManifestStart(year: string, elapsed: string): string {
  return `GET /api/export-zip-manifest year=${year} t=${elapsed}`;
}

export function zipManifestOk(
  ms: number,
  manifest: {
    units: { username: string; title?: string; account?: string }[];
    persons: { username: string; title?: string }[];
    centers: { username: string; title?: string }[];
    country?: { username?: string; title?: string };
  },
  elapsed: string
): string {
  const unit = manifest.units
    .map((item) => `${item.username} title=${item.title || ""} account=${item.account || "(none)"}`)
    .join(" | ");
  const person = manifest.persons.map((item) => `${item.username} title=${item.title || ""}`).join(" | ");
  const center = manifest.centers.map((item) => `${item.username} title=${item.title || ""}`).join(" | ");
  return `manifest ok ${ms}ms units=${manifest.units.length} [${unit}] persons=${manifest.persons.length} [${person}] centers=${manifest.centers.length} [${center}] country=${manifest.country?.username || ""} title=${manifest.country?.title || ""} t=${elapsed}`;
}

export function zipUnitStart(login: string, account: string, year: string, elapsed: string): string {
  return `START unit login=${login} account=${account || "(none)"} GET /api/unit-result-sheet?year=${year} t=${elapsed}`;
}

export function zipSheetOk(
  ms: number,
  sheet: {
    year?: number;
    activa?: unknown[];
    passiva?: unknown[];
    cash?: { rows?: unknown[] };
    total_activa?: number;
    total_passiva?: number;
  },
  elapsed: string
): string {
  return `result sheet ok ${ms}ms year=${sheet.year ?? "?"} activa=${sheet.activa?.length ?? 0} passiva=${sheet.passiva?.length ?? 0} cash=${sheet.cash?.rows?.length ?? 0} total_activa=${sheet.total_activa ?? "?"} total_passiva=${sheet.total_passiva ?? "?"} keys=${Object.keys(sheet).join(",")} t=${elapsed}`;
}

export function zipMatrixStart(folder: string, login: string, scope: string, year: string, elapsed: string): string {
  return `START ${folder} login=${login} GET /api/export-excel?year=${year}&${scope} t=${elapsed}`;
}

export function zipMatrixOk(
  ms: number,
  data: {
    has_balance?: boolean;
    year?: number;
    balance_tree?: unknown[] | null;
    result_tree?: unknown[] | null;
    resultaat?: unknown[];
    result_accounts?: unknown[];
    activa?: unknown[];
    passiva?: unknown[];
  },
  elapsed: string
): string {
  return `export-data ok ${ms}ms year=${data.year ?? "?"} has_balance=${Boolean(data.has_balance)} activa=${data.activa?.length ?? 0} passiva=${data.passiva?.length ?? 0} balance_rows=${data.balance_tree?.length ?? 0} result_rows=${data.result_tree?.length ?? data.resultaat?.length ?? 0} accounts=${data.result_accounts?.length ?? 0} keys=${Object.keys(data).join(",")} t=${elapsed}`;
}

export function zipWorkbookOk(ms: number, bytes: number, elapsed: string): string {
  return `workbook ok ${ms}ms bytes=${bytes} t=${elapsed}`;
}

export function zipPackStart(year: string, files: { name: string; bytes: Uint8Array }[], elapsed: string): string {
  const total = files.reduce((sum, file) => sum + file.bytes.length, 0);
  const names = files.map((file) => `${file.name}:${file.bytes.length}`).join(", ");
  return `year=${year} files=${files.length} bytes=${total} [${names}] t=${elapsed}`;
}

export function zipPackOk(ms: number, elapsed: string): string {
  return `download started ${ms}ms t=${elapsed}`;
}
