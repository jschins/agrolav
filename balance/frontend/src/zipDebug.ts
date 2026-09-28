/**
 * ZIP_DEBUG
 * Temporary Export-zip trace on the Resultaat window.
 * When the zip works, delete this file and every ZIP_DEBUG mark in App.tsx.
 */

function stamp(): string {
  const now = new Date();
  const p = (n: number, width = 2) => String(n).padStart(width, "0");
  return `${p(now.getHours())}:${p(now.getMinutes())}:${p(now.getSeconds())}.${p(now.getMilliseconds(), 3)}`;
}

function textOf(error: unknown): string {
  if (error instanceof Error) return `${error.name}: ${error.message}`;
  return String(error);
}

function openerLine(): string {
  const opener = window.opener;
  if (!opener) return "opener=null";
  const bits = ["opener=yes"];
  try {
    bits.push(`closed=${String(opener.closed)}`);
  } catch (error) {
    bits.push(`closed threw ${textOf(error)}`);
  }
  try {
    bits.push(`href=${opener.location.href}`);
  } catch (error) {
    bits.push(`href threw ${textOf(error)}`);
  }
  try {
    bits.push(`origin=${opener.location.origin}`);
  } catch (error) {
    bits.push(`origin threw ${textOf(error)}`);
  }
  return bits.join(" ");
}

function postLine(): string {
  if (!window.opener) return "postMessage skipped, opener is null";
  try {
    window.opener.postMessage({ type: "agrolav-export-zip", sentAt: Date.now() }, "*");
    return "postMessage agrolav-export-zip returned";
  } catch (error) {
    return `postMessage threw ${textOf(error)}`;
  }
}

/** Lines written the moment the knob is pressed, before any reply. */
export function zipStartLines(year: number | null): string[] {
  return [
    `button pressed year=${year ?? "?"} now=${Date.now()}`,
    `href=${location.href}`,
    `origin=${location.origin} path=${location.pathname} search=${location.search || "(empty)"}`,
    `referrer=${document.referrer || "(empty)"}`,
    `ua=${navigator.userAgent}`,
    `lang=${navigator.language} visibility=${document.visibilityState} online=${String(navigator.onLine)}`,
    `window=${window.innerWidth}x${window.innerHeight} screen=${screen.width}x${screen.height}`,
    `cookieChars=${document.cookie.length}`,
    openerLine(),
    postLine(),
  ].map((line) => `${stamp()} ${line}`);
}

/** One line for every window message that arrives while the zip screen is up. */
export function zipMessageLine(event: MessageEvent, index: number): string {
  const data: unknown = event.data;
  let type = typeof data as string;
  let keys = "";
  let extra = "";
  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;
    type = String(record.type || "(no type)");
    try {
      keys = Object.keys(record).join(",") || "(none)";
    } catch (error) {
      keys = `keys threw ${textOf(error)}`;
    }
    if (record.line != null) extra += ` line=${String(record.line)}`;
    if (record.detail != null) extra += ` detail=${String(record.detail)}`;
    if (record.error != null) extra += ` error=${String(record.error)}`;
    if (record.sentAt != null) extra += ` sentAt=${String(record.sentAt)} lagMs=${Date.now() - Number(record.sentAt)}`;
  } else {
    extra = ` data=${String(data).slice(0, 300)}`;
  }
  let source = "source=null";
  try {
    if (event.source) source = event.source === window.opener ? "source=opener" : "source=other";
  } catch (error) {
    source = `source threw ${textOf(error)}`;
  }
  return `${stamp()} message #${index} type=${type} origin=${event.origin || "(empty)"} ${source} keys=${keys}${extra}`;
}

export function zipPulseLine(messages: number, startedAt: number): string {
  const waited = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
  return `${stamp()} still waiting ${waited}s windowMessages=${messages} visibility=${document.visibilityState}`;
}

export function zipDoneLine(failure: string): string {
  return `${stamp()} ${failure ? `FAILED ${failure}` : "finished, download started"}`;
}
