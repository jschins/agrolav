import { Fragment, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type FormEvent, type MouseEvent, type ReactNode } from "react";
import { flushSync } from "react-dom";
import {
  ackCentralWinsRefusal,
  askHelp,
  addCategoryTerm,
  handsetDebug,
  getAuthMe,
  getCentralWinsRefusals,
  getCentraleNotifications,
  getCentraleStatus,
  getBanks,
  getCatalog,
  getExportExcel,
  getExportZipManifest,
  getUnitResultSheet,
  getExportResultaat,
  type ExportExcelData,
  type ExportExcelLine,
  type ExportResultaatData,
  type ExportResultaatAccount,
  getIpAccess,
  addIpAccess,
  deleteIpAccess,
  type IpAccessResponse,
  type IpAccessTarget,
  getMatrix,
  getSettings,
  getTransactions,
  getBookingSearchOptions,
  searchBookings,
  type BookingSearchOptions,
  type BookingSearchResult,
  getYears,
  login,
  logout,
  verifyLoginOtp,
  setPersonPassword,
  getTotpStatus,
  startTotp,
  confirmTotp,
  clearTotp,
  type TotpSetup,
  type TotpStatus,
  type BankAccount,
  type OtpChallenge,
  recalculate,
  recalculateFromScratch,
  recalculateIncremental,
  pendingTermChanges,
  crossPostings,
  calculateOpeningBalance,
  wipeYear,
  smallExpenses,
  recordModification,
  refreshAll,
  refreshPerson,
  prepareConsent,
  invalidateConsent,
  saveCatalog,
  getTransactionSplit,
  saveTransactionSplit,
  setCenter,
  updateSettings,
  updateCenterAccountTerms,
  type CentralWinsAlert,
  type CentraleSyncStatus,
  type ExportTreeGroup,
  type ExportTreeNode,
  type SyncNotification,
} from "./api";
import type {
  AccountGroup,
  CatalogCategory,
  MatrixResponse,
  RabobankExport,
  RefreshPersonResult,
  SettingsResponse,
  Transaction,
  TransactionsResponse,
} from "./types";
import { unitResultWorkbook } from "../../../balance/frontend/src/resultWorkbook.ts";
import {
  zipFailDetail,
  zipManifestOk,
  zipManifestStart,
  zipMatrixOk,
  zipMatrixStart,
  zipPackOk,
  zipPackStart,
  zipReceivedDetail,
  zipReply,
  zipSheetOk,
  zipUnitStart,
  zipWorkbookOk,
} from "./zipDebug"; // ZIP_DEBUG
import { zipStore } from "./zip";
import {
  buildXlsx,
  downloadBlob,
  euro2,
  type XlsxCell,
  type XlsxContour,
  type XlsxSheet,
  type XlsxStyle,
} from "./xlsx";
import AfschrijvingenEditor from "./AfschrijvingenEditor";
import { PriorityRulesDialog } from "./InfoDialog";
import JournalEditor from "./JournalEditor";

const CHANNEL = "boekhouding";
const REFRESH_STATUS_KEY = "boekhouding-refresh-status";
const BALANCE_CHANNEL = "agrolav-balance";
const BALANCE_WINDOW_NAME = "agrolavBalance";
const RESULT_WINDOW_NAME = "agrolavResult";
let balanceSheetWindow: Window | null = null;
let resultSheetWindow: Window | null = null;
let lastResultUrl: string | null = null;
let probeTimer: number | null = null;

function clearProbe(): void {
  if (probeTimer !== null) {
    window.clearTimeout(probeTimer);
    probeTimer = null;
  }
}

function closeBalanceSheetWindow(): void {
  clearProbe();
  let win = balanceSheetWindow && !balanceSheetWindow.closed ? balanceSheetWindow : null;
  if (!win) {
    try {
      win = window.open("", BALANCE_WINDOW_NAME);
    } catch {
      win = null;
    }
  }
  if (win) {
    try {
      win.postMessage({ type: "agrolav-close" }, "*");
    } catch {
      // ignore
    }
    try {
      win.close();
    } catch {
      // ignore
    }
  }
  balanceSheetWindow = null;
  try {
    const channel = new BroadcastChannel(BALANCE_CHANNEL);
    channel.postMessage({ type: "agrolav-close" });
    channel.close();
  } catch {
    // ignore
  }
}

function openResultSheetWindow(url: string): void {
  let win = resultSheetWindow && !resultSheetWindow.closed ? resultSheetWindow : null;
  if (win) {
    try {
      if (url !== lastResultUrl) win.location.href = url;
    } catch {
      win = null;
    }
  }
  if (!win) {
    win = window.open(url, RESULT_WINDOW_NAME);
  }
  resultSheetWindow = win;
  lastResultUrl = url;
  if (win) {
    try {
      win.focus();
    } catch {
      // window may be gone; ignore
    }
  }
}

function closeResultSheetWindow(): void {
  let win = resultSheetWindow && !resultSheetWindow.closed ? resultSheetWindow : null;
  if (!win) {
    try {
      win = window.open("", RESULT_WINDOW_NAME);
    } catch {
      win = null;
    }
  }
  if (win) {
    try {
      win.postMessage({ type: "agrolav-close" }, "*");
    } catch {
      // ignore
    }
    try {
      win.close();
    } catch {
      // ignore
    }
  }
  resultSheetWindow = null;
  lastResultUrl = null;
  try {
    const channel = new BroadcastChannel(BALANCE_CHANNEL);
    channel.postMessage({ type: "agrolav-close" });
    channel.close();
  } catch {
    // ignore
  }
}

function matrixFooterNames(matrix: MatrixResponse): { balance: string; last_booked: string } {
  return {
    balance: matrix.footers?.balance ?? "saldo",
    last_booked: matrix.footers?.last_booked ?? "datum",
  };
}

function isBookingCategoryName(name: string): boolean {
  return /^\d{4}/.test(name);
}

function isHitCategoryName(name: string, settings: SettingsResponse): boolean {
  if (!isBookingCategoryName(name)) return false;
  const role = String(settings.category_roles?.[name] ?? "").toLowerCase();
  if (role === "equity" || role === "never" || role === "profit" || role === "bank" || role === "no_hit" || role === "source" || role === "balance" || role === "last_booked") {
    return false;
  }
  return true;
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

/** Deepest level at which a post sits (root group = depth 0). */
function treeDepth(nodes: ExportTreeNode[], depth = 0): number {
  let max = depth;
  for (const node of nodes) {
    if (node.kind === "group") {
      max = Math.max(max, treeDepth(node.children, depth + 1));
    } else {
      max = Math.max(max, depth);
    }
  }
  return max;
}

/**
 * Outline rows for a parent-structured sheet. One text column per nesting
 * level, then the amount column, then — when `headers` is given — one
 * drill-down column per entry of a node's `columns` (e.g. per bank account).
 * Row 1 holds the title and, from the amount column on, the `headers`
 * (total first, then one per drill-down column). By default group names and
 * `Totaal` rows are bold and a group of two or more children closes with a
 * `Totaal <name>` row; with `totalsOnHeading` the group's total is written
 * on its heading row instead and no `Totaal` rows are emitted. `boldDepth`
 * makes every row at that depth or shallower bold and all deeper rows plain;
 * `fontSizes` gives the size per depth (the last entry keeps shrinking by 1
 * per extra level; amounts on root rows use the depth-1 size unless
 * `amountFontSize` fixes one size for every amount); `titleFontSize`
 * overrides the title size; `amountFormat` is the Excel number format for
 * amounts (values keep their cents); `levelBackgrounds` fills every row with
 * the colour for its depth (title, spacer rows and the row above each root
 * take the depth-0 colour); `blankRowAfterTitle` inserts an empty row 2;
 * `hideZeroPosts` drops posts whose amount rounds to 0,00 (and groups left
 * empty); `rowHeights` sets the row height in points per depth (the title
 * row uses the depth-0 height; depths past the list stay on Excel's auto
 * height). Roots are separated by a blank row.
 */
interface TreeSheetOptions {
  totalsOnHeading?: boolean;
  boldDepth?: number;
  fontSizes?: number[];
  amountFontSize?: number;
  titleFontSize?: number;
  amountFormat?: string;
  levelBackgrounds?: string[];
  blankRowAfterTitle?: boolean;
  hideZeroPosts?: boolean;
  rowHeights?: number[];
  /** Extra empty columns after the last amount that still get the row band. */
  trailingBandColumns?: number;
  /** Vertically centre every cell of the sheet. */
  verticalCenter?: boolean;
  /** Print posts as their label only, without the leading local_code. */
  hideCodes?: boolean;
  /** Rounded outline around each root row, spanning the full band width. */
  rootContour?: { lineColor: string; lineWidthPt?: number; cornerRadius?: number };
  /** Left indent (Excel indent units) for root labels. */
  rootIndent?: number;
  /** Thin line under each root row across the band, in this hex colour. */
  rootRule?: string;
  /**
   * Center and person sheets. Existing rows stay outline level 0 (the sheet
   * as it is now). Level 1, collapsed at first, is one row per account.
   */
  accountNames?: string[];
}

/** Balans row bands by depth, bright → faint: deeper peach, FFECBC, its midpoint to FBFDEF, FBFDEF. */
const BALANS_LEVEL_BACKGROUNDS = ["FFE2A3", "FFECBC", "FDF4D5", "FBFDEF"];

function pruneZeroPosts(nodes: ExportTreeNode[]): ExportTreeNode[] {
  const kept: ExportTreeNode[] = [];
  for (const node of nodes) {
    if (node.kind === "post") {
      if (Math.abs(node.amount) >= 0.005) kept.push(node);
      continue;
    }
    const children = pruneZeroPosts(node.children);
    if (children.length) kept.push({ ...node, children });
  }
  return kept;
}

function treeSheet(
  name: string,
  title: string,
  roots: ExportTreeGroup[],
  headers: string[] = [],
  options: TreeSheetOptions = {}
): XlsxSheet {
  const totalsOnHeading = options.totalsOnHeading === true;
  if (options.hideZeroPosts) {
    roots = pruneZeroPosts(roots).filter((n): n is ExportTreeGroup => n.kind === "group");
  }
  const levels = treeDepth(roots) + 1;
  const amountCol = levels;
  const drill = Math.max(0, headers.length - 1);
  const width = amountCol + 1 + drill + Math.max(0, options.trailingBandColumns ?? 0);
  type RowKind = "heading" | "post" | "total";
  const sizeAt = (depth: number): number | undefined => {
    const sizes = options.fontSizes;
    if (!sizes?.length) return undefined;
    if (depth < sizes.length) return sizes[depth];
    return Math.max(6, sizes[sizes.length - 1] - (depth - (sizes.length - 1)));
  };
  const backgroundAt = (depth: number): string | undefined => {
    const colors = options.levelBackgrounds;
    if (!colors?.length) return undefined;
    return colors[Math.min(depth, colors.length - 1)];
  };
  const isBold = (depth: number, kind: RowKind): boolean =>
    options.boldDepth !== undefined ? depth <= options.boldDepth : kind !== "post";
  const vCenter = options.verticalCenter === true;
  const isRootHeading = (depth: number, kind?: RowKind): boolean =>
    depth === 0 && kind === "heading";
  const textStyle = (depth: number, kind: RowKind, sizeDepth = depth): XlsxStyle => {
    const style: XlsxStyle = {};
    if (isBold(depth, kind)) style.bold = true;
    const size = sizeAt(sizeDepth) ?? (kind === "heading" && depth === 0 ? 12 : undefined);
    if (size) style.fontSize = size;
    const background = backgroundAt(depth);
    if (background) style.background = background;
    if (vCenter) style.verticalCenter = true;
    if (options.rootRule && isRootHeading(depth, kind)) style.borderBottom = options.rootRule;
    return style;
  };
  const styled = (value: string | number, style: XlsxStyle): XlsxCell =>
    Object.keys(style).length ? { value, style } : value;
  const text = (depth: number, kind: RowKind, value: string): XlsxCell => {
    const style = textStyle(depth, kind);
    if (depth === 0 && kind === "heading" && options.rootIndent) style.indent = options.rootIndent;
    return styled(value, style);
  };
  const amount = (depth: number, kind: RowKind, value: number): XlsxCell => {
    // Root-row amounts take the next level's size unless one size is fixed.
    const style = textStyle(depth, kind, Math.max(depth, 1));
    if (options.amountFontSize) style.fontSize = options.amountFontSize;
    if (options.amountFormat) style.format = options.amountFormat;
    return styled(euro2(value), style);
  };
  const blank = (depth?: number, kind?: RowKind): XlsxCell[] => {
    const background = depth === undefined ? undefined : backgroundAt(depth);
    const style: XlsxStyle = {};
    if (background) style.background = background;
    if (vCenter) style.verticalCenter = true;
    if (options.rootRule && depth !== undefined && isRootHeading(depth, kind)) {
      style.borderBottom = options.rootRule;
    }
    const filler: XlsxCell = Object.keys(style).length ? { value: "", style } : "";
    return Array.from({ length: width }, () => filler);
  };
  // Title, spacer rows and the row above each root wear the depth-0 band.
  const spacer = (): XlsxCell[] => (backgroundAt(0) ? blank(0) : []);
  const bandStyle = (): XlsxStyle => ({
    ...(backgroundAt(0) ? { background: backgroundAt(0) } : {}),
    ...(vCenter ? { verticalCenter: true } : {}),
  });
  const header = blank(0);
  header[0] = {
    value: title,
    style: {
      bold: true,
      fontSize: options.titleFontSize ?? (sizeAt(0) ?? 12) + 2,
      ...bandStyle(),
    },
  };
  headers.forEach((label, i) => {
    header[amountCol + i] = { value: label, style: { bold: true, ...bandStyle() } };
  });
  const heightAt = (depth: number): number | undefined => options.rowHeights?.[depth];
  const rows: XlsxCell[][] = [header];
  // Without account rows, outline level is the nesting depth. With them, the
  // current sheet is level 0 and each account contribution is level 1.
  const accountNames = options.accountNames;
  const outlineLevels: number[] = [0];
  const rowHidden: boolean[] = [false];
  const rowCollapsed: boolean[] = [false];
  const rowHeights: (number | undefined)[] = [heightAt(0)];
  const contours: XlsxContour[] = [];
  const push = (row: XlsxCell[], depth: number, height?: number) => {
    rows.push(row);
    outlineLevels.push(accountNames ? 0 : depth);
    rowHidden.push(false);
    rowCollapsed.push(false);
    rowHeights.push(height);
  };
  const appendAccounts = (columns: number[] | undefined, depth: number) => {
    if (!accountNames || !columns?.length) return;
    const summary = rows.length - 1;
    let any = false;
    accountNames.forEach((name, index) => {
      const value = columns[index] ?? 0;
      if (Math.abs(value) < 0.005) return;
      const parts = Array.from({ length: drill }, (_, i) => (i === index ? value : 0));
      const detail = line(depth, "post", name, value, drill ? parts : undefined);
      const label = detail[depth];
      const labelStyle = typeof label === "object" ? { ...label.style } : {};
      detail[depth] = {
        value: typeof label === "object" ? label.value : String(label ?? name),
        style: { ...labelStyle, bold: false, indent: (labelStyle.indent ?? 0) + 1 },
      };
      for (let column = amountCol; column < detail.length; column += 1) {
        const cell = detail[column];
        if (typeof cell === "object" && cell.style?.bold) {
          detail[column] = { ...cell, style: { ...cell.style, bold: false } };
        }
      }
      push(detail, depth);
      outlineLevels[outlineLevels.length - 1] = 1;
      rowHidden[rowHidden.length - 1] = true;
      any = true;
    });
    if (any) rowCollapsed[summary] = true;
  };
  if (options.blankRowAfterTitle) push(spacer(), 0);
  const line = (
    depth: number,
    kind: RowKind,
    label: string,
    value?: number,
    columns?: number[]
  ): XlsxCell[] => {
    const row = blank(depth, kind);
    row[depth] = text(depth, kind, label);
    if (value !== undefined) {
      row[amountCol] = amount(depth, kind, value);
      for (let i = 0; i < drill; i += 1) {
        row[amountCol + 1 + i] = amount(depth, kind, columns?.[i] ?? 0);
      }
    }
    return row;
  };
  const walk = (node: ExportTreeNode, depth: number) => {
    const height = heightAt(depth);
    if (node.kind === "post") {
      const label = options.hideCodes ? node.label : `${node.code} ${node.label}`;
      push(line(depth, "post", label, node.amount, node.columns), depth, height);
      appendAccounts(node.columns, depth);
      return;
    }
    if (depth === 0 && options.rootContour) {
      const rowIndex = rows.length; // zero-based index of the row about to be pushed
      contours.push({
        fromCol: 0,
        fromRow: rowIndex,
        toCol: width,
        toRow: rowIndex + 1,
        ...options.rootContour,
      });
    }
    if (totalsOnHeading) {
      push(line(depth, "heading", node.name, node.total, node.columns), depth, height);
    } else {
      push(line(depth, "heading", node.name), depth, height);
    }
    for (const child of node.children) walk(child, depth + 1);
    if (!totalsOnHeading && (node.children.length > 1 || depth === 0)) {
      push(line(depth, "total", `Totaal ${node.name}`, node.total, node.columns), depth, height);
    }
  };
  roots.forEach((root, i) => {
    if (i > 0) push(spacer(), 0);
    walk(root, 0);
  });
  const widths: number[] = Array.from({ length: levels }, (_, i) =>
    i === levels - 1 ? 44 : 4
  );
  for (let i = 0; i <= drill; i += 1) widths.push(14);
  return {
    name,
    rows,
    widths,
    outlineLevels,
    rowHidden: accountNames ? rowHidden : undefined,
    rowCollapsed: accountNames ? rowCollapsed : undefined,
    rowHeights,
    contours,
  };
}

/** Resultaat drill-down headers: one per bank account. */
function resultDrillHeaders(data: ExportExcelData, _terms: Record<string, string>): string[] {
  const accounts = resultaatAccountHeaders(data.result_accounts ?? []);
  const mirrors = (data.result_mirrors ?? []).map((m) => m.label);
  if (!accounts.length && !mirrors.length && !data.resultaat.some((l) => l.columns?.length)) {
    return [];
  }
  return [...accounts, ...mirrors];
}

function excelSheets(data: ExportExcelData, terms: Record<string, string> = {}): XlsxSheet[] {
  const sheets: XlsxSheet[] = [];
  const codeOf = (line: ExportExcelLine) => String(line.code);
  const accountHeaders = resultDrillHeaders(data, terms);
  const accountNames =
    data.account_rows && (data.result_accounts?.length ?? 0) > 0
      ? resultaatAccountHeaders(data.result_accounts ?? [])
      : undefined;
  if (data.has_balance) {
    if (data.balance_tree?.length) {
      sheets.push(
        treeSheet("Balans", `Balans ${data.year}`, data.balance_tree, [], {
          totalsOnHeading: true,
          boldDepth: 1,
          fontSizes: [16, 14, 13, 12],
          amountFontSize: 12,
          titleFontSize: 16,
          amountFormat: "#,##0",
          levelBackgrounds: BALANS_LEVEL_BACKGROUNDS,
          blankRowAfterTitle: true,
          hideZeroPosts: true,
          rowHeights: [64, 42, 27],
          trailingBandColumns: 1,
          verticalCenter: true,
          hideCodes: true,
          rootIndent: 1,
          rootRule: "595959",
          accountNames,
        })
      );
    } else {
      const rows: (string | number)[][] = [];
      rows.push([`Balans ${data.year}`]);
      rows.push(["Zijde", "Code", "Post", "Bedrag"]);
      for (const line of data.activa) {
        rows.push(["Activa", codeOf(line), line.label, euro2(line.amount)]);
      }
      rows.push(["Activa", "", "Totaal Activa", euro2(data.total_activa)]);
      rows.push([]);
      for (const line of data.passiva) {
        rows.push(["Passiva", codeOf(line), line.label, euro2(line.amount)]);
      }
      rows.push(["Passiva", "", "Totaal Passiva", euro2(data.total_passiva)]);
      sheets.push({ name: "Balans", rows, widths: [8, 10, 60, 14] });
    }
  }
  if (data.result_tree?.length) {
    sheets.push(
      treeSheet(
        "Resultaat",
        `Resultaat ${data.year}`,
        data.result_tree,
        accountHeaders.length ? ["Totaal", ...accountHeaders] : [],
        { accountNames }
      )
    );
  } else {
    const rows: (string | number)[][] = [];
    const columnTotals = accountHeaders.map(() => 0);
    rows.push([`Resultaat ${data.year}`]);
    rows.push(["Code", "Post", "Bedrag", ...accountHeaders]);
    for (const line of data.resultaat) {
      const parts = accountHeaders.map((_, i) => line.columns?.[i] ?? 0);
      parts.forEach((n, i) => {
        columnTotals[i] += n;
      });
      rows.push([codeOf(line), line.label, euro2(line.amount), ...parts.map(euro2)]);
    }
    rows.push(["", "Totaal", euro2(data.total_resultaat), ...columnTotals.map(euro2)]);
    sheets.push({
      name: "Resultaat",
      rows,
      widths: [10, 60, 14, ...accountHeaders.map(() => 14)],
    });
  }
  return sheets;
}

const RESULTAAT_MONTHS = [
  "Januari",
  "Februari",
  "Maart",
  "April",
  "Mei",
  "Juni",
  "Juli",
  "Augustus",
  "September",
  "Oktober",
  "November",
  "December",
];

function resultaatVisibleMonthCount(year: number, reported?: number): number {
  const now = new Date();
  let cap = 12;
  if (year > now.getFullYear()) cap = 0;
  else if (year === now.getFullYear()) cap = now.getMonth() + 1;
  if (typeof reported === "number" && reported >= 0 && reported <= 12) {
    return Math.min(reported, cap);
  }
  return cap;
}

function resultaatSections(data: ExportResultaatData): {
  title: string;
  header: (string | number)[];
  body: (string | number)[][];
  /** Month columns whose three Resultaat lines do not add up to Banksaldo. */
  mismatch?: boolean[];
}[] {
  const monthCount = resultaatVisibleMonthCount(data.year, data.month_count);
  const monthNames = RESULTAAT_MONTHS.slice(0, monthCount);
  const header: (string | number)[] = ["Code", "Post", ...monthNames, "Cumulatief"];
  const padMonths = (raw: number[] | undefined): number[] => {
    const next = [...(raw ?? [])];
    while (next.length < monthCount) next.push(0);
    return next.slice(0, monthCount);
  };
  const sections: {
    title: string;
    header: (string | number)[];
    body: (string | number)[][];
    mismatch?: boolean[];
  }[] = [];

  const categoryBody: (string | number)[][] = [];
  const saldoMonths = Array.from({ length: monthCount }, () => 0);
  const hdCash = data.cashflow_1053?.stichting ? data.cashflow_1053 : null;
  if (hdCash && data.incoming_1053) {
    const parts = padMonths(data.incoming_1053.months);
    if (parts.some((n) => n !== 0)) {
      const monthSum = parts.reduce((sum, n) => sum + n, 0);
      categoryBody.push([
        String(data.incoming_1053.code),
        data.incoming_1053.label,
        ...parts.map((n) => euro2(n)),
        euro2(monthSum),
      ]);
    }
  }
  for (const line of data.resultaat) {
    const parts = padMonths(line.months);
    const monthSum = parts.reduce((sum, n) => sum + n, 0);
    const cumul = parts.some((n) => n !== 0) ? monthSum : line.amount;
    categoryBody.push([
      String(line.code),
      line.label,
      ...parts.map((n) => euro2(n)),
      euro2(cumul),
    ]);
    for (let i = 0; i < monthCount; i++) saldoMonths[i] += parts[i];
  }
  const saldoCumul = saldoMonths.reduce((sum, n) => sum + n, 0);
  categoryBody.push([
    "",
    hdCash ? "Saldo" : "Totaal",
    ...saldoMonths.map((n) => euro2(n)),
    euro2(saldoCumul),
  ]);
  if (hdCash && data.maaltijden) {
    const ont = padMonths(data.maaltijden.ontbijten);
    const koude = padMonths(data.maaltijden.koude);
    const warme = padMonths(data.maaltijden.warme);
    const warmHd = padMonths(data.maaltijden.warm_hd);
    const foodLine = data.resultaat.find((line) => line.code === 3035);
    const food = padMonths(foodLine?.months);
    const foodCumul = food.some((n) => n !== 0)
      ? food.reduce((sum, n) => sum + n, 0)
      : (foodLine?.amount ?? 0);
    const ontCumul = ont.reduce((sum, n) => sum + n, 0);
    const koudeCumul = koude.reduce((sum, n) => sum + n, 0);
    const warmeCumul = warme.reduce((sum, n) => sum + n, 0);
    const warmHdCumul = warmHd.reduce((sum, n) => sum + n, 0);
    const equivalent = (o: number, k: number, w: number, wh: number): number =>
      (o + 2 * k + 3 * w + 3 * wh) / 6;
    const costCell = (foodAmt: number, eq: number): number | "" =>
      eq === 0 ? "" : euro2(-(foodAmt / eq));
    const countRow = (label: string, parts: number[], cumul: number) => {
      categoryBody.push(["", label, ...parts.map((n) => euro2(n)), euro2(cumul)]);
    };
    categoryBody.push([]);
    countRow("Aantal ontbijten", ont, ontCumul);
    countRow("Aantal koude maaltijden", koude, koudeCumul);
    countRow("Aantal warme maaltijden", warme, warmeCumul);
    countRow("Aantal warme maaltijden hd", warmHd, warmHdCumul);
    const equivMonths = ont.map((_, i) =>
      equivalent(ont[i], koude[i], warme[i], warmHd[i])
    );
    const equivCumul = equivalent(ontCumul, koudeCumul, warmeCumul, warmHdCumul);
    categoryBody.push([
      "",
      "Equivalent aantal tafelgenoten",
      ...equivMonths.map((n) => euro2(n)),
      euro2(equivCumul),
    ]);
    categoryBody.push([
      "",
      "Voedselkosten per tafelgenoot",
      ...equivMonths.map((eq, i) => costCell(food[i], eq)),
      costCell(foodCumul, equivCumul),
    ]);
  }
  if (hdCash) {
    const opening = padMonths(hdCash.opening?.months);
    const stichting = padMonths(hdCash.stichting?.months);
    const income = padMonths(hdCash.inkomsten?.months);
    const spent = padMonths(hdCash.uitgaven?.months);
    const movement = padMonths(hdCash.resultaat?.months);
    const closing = padMonths(hdCash.banksaldo?.months);
    const stock = (label: string, parts: number[]) => {
      categoryBody.push(["", label, ...parts.map((n) => euro2(n)), ""]);
    };
    const flow = (label: string, parts: number[]) => {
      const cumul = parts.reduce((sum, n) => sum + n, 0);
      categoryBody.push(["", label, ...parts.map((n) => euro2(n)), euro2(cumul)]);
    };
    categoryBody.push([]);
    stock("Beginsaldo", opening);
    flow("Stichting de Oude Gracht", stichting);
    flow("Overige inkomsten", income);
    flow("Uitgaven", spent);
    flow("Resultaat", movement);
    categoryBody.push([]);
    stock("Banksaldo einde maand", closing);
    sections.push({ title: "Resultaat", header, body: categoryBody });
  } else {
    sections.push({ title: "Resultaat", header, body: categoryBody });
  }

  if (data.cashflow_1053 && !hdCash) {
    const opening = padMonths(data.cashflow_1053.opening?.months);
    const other = padMonths(data.cashflow_1053.other?.months);
    const closing = padMonths(data.cashflow_1053.banksaldo?.months);
    const cents = (n: number) => Math.round((n + Number.EPSILON) * 100);
    const mismatch = saldoMonths.map(
      (total, i) => cents(opening[i] + other[i] + total) !== cents(closing[i])
    );
    const balanceHeader: (string | number)[] = ["Code", "Post", ...monthNames];
    const cashBody: (string | number)[][] = [
      ["", "Beginsaldo", ...opening.map((n) => euro2(n))],
      ["", "Overige mutaties", ...other.map((n) => euro2(n))],
      ["", "Resultaat", ...saldoMonths.map((n) => euro2(n))],
      [],
      ["", "Banksaldo einde maand", ...closing.map((n) => euro2(n))],
    ];
    sections.push({
      title: "Balans",
      header: balanceHeader,
      body: cashBody,
      mismatch,
    });
  }
  if (data.maaltijden && !hdCash) {
    const ont = padMonths(data.maaltijden.ontbijten);
    const koude = padMonths(data.maaltijden.koude);
    const warme = padMonths(data.maaltijden.warme);
    const warmHd = padMonths(data.maaltijden.warm_hd);
    const foodLine = data.resultaat.find((line) => line.code === 3035);
    const food = padMonths(foodLine?.months);
    const foodCumul = food.some((n) => n !== 0)
      ? food.reduce((sum, n) => sum + n, 0)
      : (foodLine?.amount ?? 0);
    const ontCumul = ont.reduce((sum, n) => sum + n, 0);
    const koudeCumul = koude.reduce((sum, n) => sum + n, 0);
    const warmeCumul = warme.reduce((sum, n) => sum + n, 0);
    const warmHdCumul = warmHd.reduce((sum, n) => sum + n, 0);
    const equivalent = (o: number, k: number, w: number, wh: number): number =>
      (o + 2 * k + 3 * w + 3 * wh) / 6;
    const costCell = (foodAmt: number, eq: number): number | "" =>
      eq === 0 ? "" : euro2(-(foodAmt / eq));
    const mealBody: (string | number)[][] = [];
    const countRow = (label: string, parts: number[], cumul: number) => {
      mealBody.push(["", label, ...parts.map((n) => euro2(n)), euro2(cumul)]);
    };
    countRow("Aantal ontbijten", ont, ontCumul);
    countRow("Aantal koude maaltijden", koude, koudeCumul);
    countRow("Aantal warme maaltijden", warme, warmeCumul);
    countRow("Aantal warme maaltijden hd", warmHd, warmHdCumul);
    const equivMonths = ont.map((_, i) =>
      equivalent(ont[i], koude[i], warme[i], warmHd[i])
    );
    const equivCumul = equivalent(ontCumul, koudeCumul, warmeCumul, warmHdCumul);
    mealBody.push([
      "",
      "Equivalent aantal tafelgenoten",
      ...equivMonths.map((n) => euro2(n)),
      euro2(equivCumul),
    ]);
    mealBody.push([
      "",
      "Voedselkosten per tafelgenoot",
      ...equivMonths.map((eq, i) => costCell(food[i], eq)),
      costCell(foodCumul, equivCumul),
    ]);
    sections.push({ title: "Maaltijden", header, body: mealBody });
  }
  return sections;
}

/** Column headers: account name, suffixed with the person when names repeat. */
function resultaatAccountHeaders(accounts: ExportResultaatAccount[]): string[] {
  const nameOf = (a: ExportResultaatAccount): string =>
    a.account_name.trim() || (a.iban || "").trim() || String(a.account_id);
  const counts = new Map<string, number>();
  for (const a of accounts) {
    const name = nameOf(a);
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return accounts.map((a) => {
    const name = nameOf(a);
    const person = (a.person || "").trim();
    return (counts.get(name) ?? 0) > 1 && person ? `${name} (${person})` : name;
  });
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

function amountHasValue(raw: string): boolean {
  const t = raw.trim();
  if (!t) return false;
  const n = Number(t.replace(",", "."));
  return Number.isFinite(n) && n !== 0;
}

function categoryHasAmounts(matrix: MatrixResponse, category: string, person?: string): boolean {
  const names = person ? [person] : matrix.people.map((p) => p.person_name);
  return names.some((name) => amountHasValue(matrix.cells[category]?.[name] ?? ""));
}

function personHasTransactions(matrix: MatrixResponse, category: string, person: string): boolean {
  if (matrix.used !== undefined) {
    return (matrix.used[category] ?? []).includes(person);
  }
  return amountHasValue(matrix.cells[category]?.[person] ?? "");
}

function categoryHasTransactions(
  matrix: MatrixResponse,
  category: string,
  person?: string
): boolean {
  if (person) return personHasTransactions(matrix, category, person);
  if (matrix.used !== undefined) {
    return (matrix.used[category]?.length ?? 0) > 0;
  }
  return categoryHasAmounts(matrix, category);
}

function categoryRowGreyed(matrix: MatrixResponse, category: string, person?: string): boolean {
  if (isMatrixFooter(matrix, category)) return false;
  return !categoryHasTransactions(matrix, category, person);
}

/** Center, person, and unit views drop unused categories and the saldo/datum footers. */
function matrixRowsToShow(
  matrix: MatrixResponse,
  person: string | undefined,
  omitEmpty: boolean
): string[] {
  if (!omitEmpty) return matrix.categories;
  return matrix.categories.filter((cat) => {
    if (isMatrixFooter(matrix, cat)) return false;
    return !categoryRowGreyed(matrix, cat, person);
  });
}

function scopedAccountGroups(
  groups: AccountGroup[] | undefined,
  personScope?: string
): AccountGroup[] {
  const all = groups ?? [];
  const needle = (personScope || "").trim().toLowerCase();
  if (!needle) return all;
  return all.filter(
    (group) => String(group.person || "").trim().toLowerCase() === needle
  );
}

function bookingContainsTerm(row: Transaction, term: string): boolean {
  const haystack = `${String(row.name ?? "")}\n${String(row.description ?? "")}`;
  const parts = term
    .trim()
    .toLowerCase()
    .split(" && ")
    .map((part) => part.trim())
    .filter(Boolean);
  if (!parts.length) return false;
  return parts.every((part) => {
    if (part.includes("#") && !part.includes(" ")) {
      return haystack.split(/\s+/).some((word) => matchesHashWord(part, word));
    }
    const re = new RegExp(`\\b${escapeRegExp(part)}\\b`, "i");
    return re.test(haystack);
  });
}

function bookingLeavesCategory(row: Transaction, term: string, rowId?: string): boolean {
  if (rowId && String(row.id ?? "") === rowId) return true;
  return bookingContainsTerm(row, term);
}

function handModification(prior: number, change: "category" | "description"): number {
  const categoryHand = change === "category" || prior === 2 || prior === 4;
  const descriptionHand = change === "description" || prior === 3 || prior === 4;
  if (categoryHand && descriptionHand) return 4;
  if (descriptionHand) return 3;
  if (categoryHand) return 2;
  return prior;
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

function sortMenuItems(items: HeaderAction[]): HeaderAction[] {
  return [...items].sort((a, b) =>
    a.label.trim().localeCompare(b.label.trim(), undefined, { sensitivity: "base" })
  );
}

function menuBitOn(value: boolean | number | string | null | undefined): boolean {
  if (value === true || value === 1) return true;
  const text = String(value ?? "").trim().toLowerCase();
  return text === "1" || text === "true";
}

function menuItemAllowed(
  id: string,
  access: string,
  rows: CentraleSyncStatus["menu_items"],
  administrator?: boolean
): boolean {
  if (administrator) return true;
  const row = (rows ?? []).find((item) => item.menu_id === id);
  if (!row) return false;
  if (access === "country") return menuBitOn(row.country);
  if (access === "local") return menuBitOn(row.center);
  if (access === "personal") return menuBitOn(row.person);
  if (access === "unit") return menuBitOn(row.unit);
  return false;
}

type AppView =
  | "main"
  | "terms"
  | "categories"
  | "ip"
  | "split"
  | "password"
  | "journal"
  | "afschrijvingen"
  | "search"
  | "monthly";

const VIEW_CHANGE_EVENT = "boekhouding-view";

const HeaderActionsContext = createContext<(items: HeaderAction[]) => void>(() => {});
const NoteRescoreQueuedContext = createContext<() => void>(() => {});

type BanksFlags = {
  person?: string;
  first_download: boolean;
  needs_initial_authorization: boolean;
  enable_debug?: Record<string, unknown>;
};

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
  accounts,
  onSelect,
  terms,
}: {
  view: string;
  accounts: BankAccount[];
  onSelect: (v: string) => void;
  terms?: Record<string, string>;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  const consolidatedLabel = tableHeaderTerm(terms, "Consolidated");
  const triggerLabel = view === "consolidated" ? consolidatedLabel : view;

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
        <span className="center-switcher-label">{triggerLabel}</span>
      </button>
      {open && (
        <ul className="center-switcher-menu" role="listbox">
          <li key="consolidated">
            <button
              type="button"
              role="option"
              aria-selected={view === "consolidated"}
              className={view === "consolidated" ? "is-selected" : undefined}
              onClick={() => {
                setOpen(false);
                if (view !== "consolidated") onSelect("consolidated");
              }}
            >
{consolidatedLabel}
            </button>
          </li>
          {accounts.map((acc) => (
            <li key={acc.iban}>
              <button
                type="button"
                role="option"
                aria-selected={acc.iban === view}
                className={acc.iban === view ? "is-selected" : undefined}
                onClick={() => {
                  setOpen(false);
                  if (acc.iban !== view) onSelect(acc.iban);
                }}
              >
                {acc.iban}
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

function ActionsMenu({
  items,
  busy = false,
  onPick,
}: {
  items: HeaderAction[];
  busy?: boolean;
  onPick: (item: HeaderAction) => void;
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

  if (items.length === 0) return null;

  return (
    <div className="center-switcher actions-menu" ref={rootRef}>
      <button
        type="button"
        className="center-switcher-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={busy}
        onClick={() => {
          if (busy) return;
          setOpen((v) => !v);
        }}
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
                className={isLogoutItem(item) ? "menu-logout" : undefined}
                disabled={item.disabled}
                onClick={() => {
                  if (item.disabled || busy) return;
                  setOpen(false);
                  onPick(item);
                }}
              >
                <RichLabel text={item.label} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function LoggedInUsers({ names }: { names: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="center-switcher logged-in-users">
      <button
        type="button"
        className="center-switcher-trigger"
        aria-expanded={open}
        aria-label={`${names.length} other users logged in`}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          setOpen(true);
        }}
        onPointerUp={() => setOpen(false)}
        onPointerCancel={() => setOpen(false)}
        onLostPointerCapture={() => setOpen(false)}
        onContextMenu={(event) => event.preventDefault()}
      >
        <span className="center-switcher-chevron" aria-hidden>
          ▾
        </span>
        <span className="center-switcher-label">{names.length}</span>
      </button>
      {open ? (
        <ul className="center-switcher-menu logged-in-users-menu" role="list">
          {names.map((name) => (
            <li key={name}>{name}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function isLogoutItem(item: HeaderAction): boolean {
  if (item.id === "logout") return true;
  const label = item.label.trim().toLowerCase();
  return label === "logout" || label === "uitloggen" || label === "log out";
}

function helpInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let last = 0;
  let key = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > last) nodes.push(text.slice(last, index));
    const token = match[0];
    if (token.startsWith("`")) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    }
    key += 1;
    last = index + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function helpTable(block: string, key: number) {
  const lines = block
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("|"));
  const parsed = lines
    .filter((line) => {
      const cells = line.replace(/^\|/, "").replace(/\|$/, "").split("|");
      return !cells.every((cell) => /^\s*:?-{3,}:?\s*$/.test(cell));
    })
    .map((line) =>
      line
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => cell.trim())
    );
  if (parsed.length === 0) return <p key={key}>{helpInline(block)}</p>;
  const [head, ...body] = parsed;
  return (
    <table key={key}>
      <thead>
        <tr>
          {head.map((cell, index) => (
            <th key={index}>{helpInline(cell)}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {body.map((row, rowIndex) => (
          <tr key={rowIndex}>
            {row.map((cell, index) => (
              <td key={index}>{helpInline(cell)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function HelpMarkdown({ text }: { text: string }) {
  const blocks = text.replace(/\r\n/g, "\n").split(/\n\s*\n/);
  return (
    <>
      {blocks.map((block, key) => {
        const trimmed = block.trim();
        if (!trimmed) return null;
        if (/^-{3,}$/.test(trimmed)) return <hr key={key} />;
        const docName = /^@@\s+(\S.*)$/.exec(trimmed);
        if (docName && !trimmed.includes("\n")) {
          return (
            <h2 key={key} className="help-question-doc">
              {docName[1]}
            </h2>
          );
        }
        if (trimmed.startsWith("|")) return helpTable(trimmed, key);
        const heading = /^(#{1,6})\s+(\S.*)$/.exec(trimmed);
        if (heading && !trimmed.includes("\n")) {
          const Tag = heading[1].length <= 2 ? "h2" : "h3";
          return <Tag key={key}>{helpInline(heading[2])}</Tag>;
        }
        const lines = trimmed.split("\n");
        if (lines.every((line) => /^\s*[-*]\s+/.test(line))) {
          return (
            <ul key={key}>
              {lines.map((line, index) => (
                <li key={index}>{helpInline(line.replace(/^\s*[-*]\s+/, ""))}</li>
              ))}
            </ul>
          );
        }
        if (lines.every((line) => /^\s*\d+\.\s+/.test(line))) {
          return (
            <ol key={key}>
              {lines.map((line, index) => (
                <li key={index}>{helpInline(line.replace(/^\s*\d+\.\s+/, ""))}</li>
              ))}
            </ol>
          );
        }
        return <p key={key}>{helpInline(trimmed.replace(/\n/g, " "))}</p>;
      })}
    </>
  );
}

function HelpQuestion({ terms }: { terms?: Record<string, string> }) {
  const prompt = tableHeaderTerm(terms, "Question about this program");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (ev: globalThis.MouseEvent) => {
      if (!boxRef.current?.contains(ev.target as Node)) setOpen(false);
    };
    const onKey = (ev: globalThis.KeyboardEvent) => {
      if (ev.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const submit = () => {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setError("");
    setOpen(true);
    void askHelp(q)
      .then((res) => {
        setAnswer(res.answer);
      })
      .catch(() => {
        setAnswer("");
        setError("Could not answer that just now.");
      })
      .finally(() => setBusy(false));
  };

  return (
    <div className="help-question" ref={boxRef}>
      <input
        className="help-question-input"
        type="text"
        value={question}
        placeholder={prompt}
        aria-label={prompt}
        disabled={busy}
        onChange={(ev) => setQuestion(ev.target.value)}
        onKeyDown={(ev) => {
          if (ev.key === "Enter") {
            ev.preventDefault();
            submit();
          }
        }}
      />
      {open ? (
        <div className="help-question-answer" role="status">
          {busy ? "…" : error ? error : <HelpMarkdown text={answer} />}
        </div>
      ) : null}
    </div>
  );
}

function overviewFilename(username: string): string {
  const now = new Date();
  const day = String(now.getDate()).padStart(2, "0");
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const safe = username.trim().replace(/[\\/:*?"<>|]/g, "_") || "login";
  return `overzicht ${safe} ${day}-${month}-${now.getFullYear()}.xlsx`;
}

function SyncNotifyShell({
  children,
  onCenterChanged,
  termsView = false,
  categoriesView = false,
  ipView = false,
  splitView = false,
  passwordView = false,
  journalView = false,
  afschrijvingenView = false,
  searchView = false,
  onLogout,
  initialTitle = "",
}: {
  children: (
    brandName: string,
    activeYear: string,
    bankView: string,
    dataRev: number,
    banks: BanksFlags,
    bankOptions: BankAccount[],
    menuTerms: Record<string, string>
  ) => ReactNode;
  onCenterChanged?: () => void;
  termsView?: boolean;
  categoriesView?: boolean;
  ipView?: boolean;
  splitView?: boolean;
  passwordView?: boolean;
  journalView?: boolean;
  afschrijvingenView?: boolean;
  searchView?: boolean;
  onLogout?: () => void;
  initialTitle?: string;
}) {
  const [status, setStatus] = useState<CentraleSyncStatus | null>(null);
  const [notes, setNotes] = useState<SyncNotification[]>([]);
  const [switching, setSwitching] = useState(false);
  const [activeYear, setActiveYear] = useState<string>("");
  const [yearOptions, setYearOptions] = useState<string[]>([]);
  const [bankView, setBankView] = useState<string>("consolidated");
  const [bankOptions, setBankOptions] = useState<BankAccount[]>([]);
  const [showBankSwitcher, setShowBankSwitcher] = useState(false);
  const [uploadUrl, setUploadUrl] = useState<string>("");
  const [refusal, setRefusal] = useState<CentralWinsAlert | null>(null);
  const [headerActions, setHeaderActions] = useState<HeaderAction[]>([]);
  const [scratchBusy, setScratchBusy] = useState(false);
  const [scratchError, setScratchError] = useState<string | null>(null);
  const [wipeBusy, setWipeBusy] = useState(false);
  const [crossBusy, setCrossBusy] = useState(false);
  const [openingBusy, setOpeningBusy] = useState(false);
  const [wipeError, setWipeError] = useState<string | null>(null);
  const [wipeOpen, setWipeOpen] = useState(false);
  const [smallOpen, setSmallOpen] = useState<"expense" | "income" | null>(null);
  const [recalcOpen, setRecalcOpen] = useState(false);
  const [wipeScope, setWipeScope] = useState<{ person?: string; account?: string }>({});
  const [rescoreError, setRescoreError] = useState<string | null>(null);
  const noteRescoreQueued = useCallback(() => {
    setRescoreError(null);
  }, []);
  const [dataRev, setDataRev] = useState(0);
  const dataEpochRef = useRef<number | null>(null);
  const [menuTerms, setMenuTerms] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((res) => {
        if (!cancelled) setMenuTerms(res.table_header_terms);
      })
      .catch(() => {
        if (!cancelled) setMenuTerms({});
      });
    return () => {
      cancelled = true;
    };
  }, [status?.center, dataRev]);

  const [banksState, setBanksState] = useState<BanksFlags>({
    first_download: false,
    needs_initial_authorization: false,
  });

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
    const unitAccount = (status?.account || "").trim();
    if ((access !== "personal" && access !== "unit") || !activeYear) {
      setShowBankSwitcher(false);
      setBankOptions([]);
      setBankView("consolidated");
      setUploadUrl("");
      setBanksState({
        first_download: false,
        needs_initial_authorization: false,
        enable_debug: { ui_skip: "access_not_personal_or_no_year", access },
      });
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
          const folders = res.folders || [];
          setShowBankSwitcher(
            access !== "unit" &&
              (Boolean(res.show_switcher) || folders.length > 1)
          );
          setBankOptions(folders);
          setBankView((prev) => {
            if (access === "unit") {
              return unitAccount || folders[0]?.iban || prev;
            }
            if (prev === "consolidated") return prev;
            if (folders.some((f) => f.iban === prev)) return prev;
            return "consolidated";
          });
          setBanksState({
            person: person || undefined,
            first_download: res.first_download === true,
            needs_initial_authorization: res.needs_initial_authorization === true,
            enable_debug: res.enable_debug,
          });
        })
        .catch((e: Error) => {
          if (cancelled) return;
          setShowBankSwitcher(false);
          setBankOptions([]);
          setUploadUrl("");
          setBanksState({
            first_download: false,
            needs_initial_authorization: false,
            enable_debug: { ui_error: e.message },
          });
        });
    }
    loadBanks();
    const id = window.setInterval(loadBanks, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [status?.access, status?.account, activeYear, status?.center, status?.person, status?.centrale_url]);

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

  function doRecalculate(mode: "scratch" | "incremental") {
    if (scratchBusy || wipeBusy || crossBusy) return;
    setRecalcOpen(false);
    beginRefreshBusy("please wait... recalculating categories");
    flushSync(() => {
      setScratchBusy(true);
      setScratchError(null);
    });
    afterPaint(() => {
      const run = mode === "incremental" ? recalculateIncremental() : recalculateFromScratch();
      run
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

  function exportExcel() {
    if (!activeYear) return;
    setScratchError(null);
    getExportExcel(activeYear)
      .then((data) => {
        downloadBlob(overviewFilename(status?.username || ""), buildXlsx(excelSheets(data, menuTerms)));
      })
      .catch((e: Error) => setScratchError(e.message));
  }

  async function exportZip(report: (line: string, detail: string) => void): Promise<string | null> {
    if (!activeYear) return "No year selected";
    setScratchError(null);
    let current = "startup";
    const started = performance.now();
    const elapsed = () => `${Math.round(performance.now() - started)}ms`;
    try {
      current = "manifest";
      report("Reading logins", zipManifestStart(activeYear, elapsed())); // ZIP_DEBUG
      const manifestAt = performance.now();
      const manifest = await getExportZipManifest();
      report(
        "Reading logins",
        zipManifestOk(Math.round(performance.now() - manifestAt), manifest, elapsed())
      ); // ZIP_DEBUG
      const files: { name: string; bytes: Uint8Array }[] = [];
      type ZipJob = {
        folder: string;
        username: string;
        title: string;
        account: string;
        scope?: { person?: string; center?: string };
      };
      const jobs: ZipJob[] = [
        ...manifest.units.map((item) => ({
          folder: "unit",
          username: item.username,
          title: item.title || item.username,
          account: item.account || "",
        })),
        ...manifest.persons.map((item) => ({
          folder: "person",
          username: item.username,
          title: item.title || item.username,
          account: "",
          scope: { person: item.username },
        })),
        ...manifest.centers.map((item) => ({
          folder: "center",
          username: item.username,
          title: item.title || item.username,
          account: "",
          scope: { center: item.username },
        })),
        ...(manifest.country?.username
          ? [{
              folder: "country",
              username: manifest.country.username,
              title: manifest.country.title || manifest.country.username,
              account: "",
            }]
          : []),
      ];
      for (let index = 0; index < jobs.length; index += 1) {
        const job = jobs[index];
        const file = overviewFilename(job.username);
        const place = `${index + 1}/${jobs.length}`;
        current = file;
        if (job.folder === "unit") {
          report(`Writing ${file} (${place})`, zipUnitStart(job.username, job.account, activeYear, elapsed())); // ZIP_DEBUG
          const fetchAt = performance.now();
          const sheet = await getUnitResultSheet(activeYear, job.username, job.account);
          report(`Writing ${file} (${place})`, zipSheetOk(Math.round(performance.now() - fetchAt), sheet, elapsed())); // ZIP_DEBUG
          const buildAt = performance.now();
          const bytes = new Uint8Array(await unitResultWorkbook(sheet, job.title).arrayBuffer());
          report(`Writing ${file} (${place})`, zipWorkbookOk(Math.round(performance.now() - buildAt), bytes.length, elapsed())); // ZIP_DEBUG
          files.push({ name: file, bytes });
          continue;
        }
        const scopeText = job.scope?.person
          ? `person=${job.scope.person}`
          : job.scope?.center
            ? `center_name=${job.scope.center}`
            : "country scope";
        report(
          `Writing ${file} (${place})`,
          zipMatrixStart(job.folder, job.username, scopeText, activeYear, elapsed())
        ); // ZIP_DEBUG
        const fetchAt = performance.now();
        const data = await getExportExcel(activeYear, job.scope);
        report(`Writing ${file} (${place})`, zipMatrixOk(Math.round(performance.now() - fetchAt), data, elapsed())); // ZIP_DEBUG
        const buildAt = performance.now();
        const bytes = new Uint8Array(await buildXlsx(excelSheets(data, menuTerms)).arrayBuffer());
        report(`Writing ${file} (${place})`, zipWorkbookOk(Math.round(performance.now() - buildAt), bytes.length, elapsed())); // ZIP_DEBUG
        files.push({ name: file, bytes });
      }
      current = "zip";
      report(`Packing export-${activeYear}.zip`, zipPackStart(activeYear, files, elapsed())); // ZIP_DEBUG
      const packAt = performance.now();
      downloadBlob(`export-${activeYear}.zip`, zipStore(files));
      report(`Packing export-${activeYear}.zip`, zipPackOk(Math.round(performance.now() - packAt), elapsed())); // ZIP_DEBUG
      return null;
    } catch (e) {
      const text = zipFailDetail(current, elapsed(), e); // ZIP_DEBUG
      report("Export zip failed", text);
      setScratchError(text);
      return text;
    }
  }

  useEffect(() => {
    function onExportRequest(e: MessageEvent) {
      if (e.data?.type === "agrolav-export-excel") exportExcel();
      if (e.data?.type === "agrolav-export-zip") {
        const source = e.source;
        const report = (line: string, detail: string) => {
          zipReply(source, { type: "agrolav-export-zip-progress", line, detail, sentAt: Date.now() }); // ZIP_DEBUG
        };
        report("Export zip", zipReceivedDetail(e, activeYear || "")); // ZIP_DEBUG
        void exportZip(report).then((message) => {
          zipReply(source, { type: "agrolav-export-zip-done", error: message, sentAt: Date.now() }); // ZIP_DEBUG
        });
      }
    }
    window.addEventListener("message", onExportRequest);
    return () => window.removeEventListener("message", onExportRequest);
  }, [activeYear, menuTerms, status?.username]);

  function doOpeningBalance() {
    if (scratchBusy || wipeBusy || crossBusy || openingBusy) return;
    const dutch = uiIsDutch(menuTerms);
    const raw = window.prompt(
      dutch ? "Jaar" : "Year",
      String(new Date().getFullYear() + 1)
    );
    if (raw == null) return;
    const year = Number(raw.trim());
    if (!Number.isInteger(year)) {
      setScratchError(dutch ? "Geef een jaar" : "Enter a year");
      return;
    }
    beginRefreshBusy(dutch ? "Beginbalans berekenen…" : "Calculating opening balance…");
    flushSync(() => setOpeningBusy(true));
    afterPaint(() => {
      calculateOpeningBalance(year)
        .then(() => {
          onCenterChanged?.();
        })
        .catch((e: Error) => setScratchError(e.message))
        .finally(() => {
          setOpeningBusy(false);
          endRefreshBusy();
        });
    });
  }

  function doCrossPostings() {
    if (scratchBusy || wipeBusy || crossBusy) return;
    beginRefreshBusy("please wait... cross-postings");
    flushSync(() => setCrossBusy(true));
    afterPaint(() => {
      crossPostings()
        .then(() => {
          onCenterChanged?.();
        })
        .catch((e: Error) => setScratchError(e.message))
        .finally(() => {
          setCrossBusy(false);
          endRefreshBusy();
        });
    });
  }

  function doWipeYear() {
    if (scratchBusy || wipeBusy || crossBusy) return;
    const dutch = uiIsDutch(menuTerms);
    const extra: { person?: string; account?: string } = {};
    if (access === "unit") {
      extra.account = (status?.account || bankView || "").trim();
    } else if (access === "personal") {
      if (!bankView || bankView === "consolidated") {
        setWipeError(dutch ? "Kies eerst een rekening" : "Select an account first");
        return;
      }
      extra.account = bankView;
    }
    setWipeError(null);
    setWipeScope(extra);
    setWipeOpen(true);
  }

  function runWipe(choices: WipeFlags) {
    setWipeOpen(false);
    beginRefreshBusy("please wait... wiping");
    flushSync(() => {
      setWipeBusy(true);
      setWipeError(null);
    });
    afterPaint(() => {
      wipeYear({ ...choices, ...wipeScope })
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

  const requestLogout = useCallback(() => {
    pendingTermChanges()
      .then((res) => {
        if ((res.changes ?? 0) <= 0) {
          onLogout?.();
          return;
        }
        beginRefreshBusy(tableHeaderTerm(menuTerms, "recalculating categories before logging out..."));
        recalculateFromScratch()
          .then(() => onLogout?.())
          .catch((e: Error) => setScratchError(e.message))
          .finally(() => endRefreshBusy());
      })
      .catch(() => onLogout?.());
  }, [onLogout, menuTerms]);

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
      label: `${tableHeaderTerm(menuTerms, "Edit Terms")} (Alt+T)`,
      onClick: () => openView("terms"),
    });
    items.push({
      id: "recalculate-categories",
      label: scratchBusy
        ? "Recalculating…"
        : tableHeaderTerm(menuTerms, "Recalculate"),
      disabled: scratchBusy || wipeBusy || crossBusy,
      onClick: () => setRecalcOpen(true),
    });
    if (status?.balance_url) {
      items.push({
        id: "cross-postings",
        label: crossBusy ? "…" : tableHeaderTerm(menuTerms, "Calculate cross-postings"),
        disabled: scratchBusy || wipeBusy || crossBusy,
        onClick: doCrossPostings,
      });
      items.push({
        id: "journal",
        label: tableHeaderTerm(menuTerms, "Manual journal posts"),
        onClick: () => openView("journal"),
      });
      items.push({
        id: "afschrijvingen",
        label: tableHeaderTerm(menuTerms, "Automatic journal posts"),
        onClick: () => openView("afschrijvingen"),
      });
      items.push({
        id: "calculate-opening-balance",
        label: openingBusy
          ? "…"
          : tableHeaderTerm(menuTerms, "Calculate opening balance"),
        disabled: scratchBusy || wipeBusy || crossBusy || openingBusy,
        onClick: doOpeningBalance,
      });
    }
    items.push({
      id: "search-statements",
      label: tableHeaderTerm(menuTerms, "Search statements"),
      onClick: () => openView("search"),
    });
    if (status?.result_url) {
      items.push({
        id: "profit-loss",
        label: tableHeaderTerm(menuTerms, "Profit/Loss"),
        onClick: () => openResultSheetWindow(status.result_url!),
      });
    }
    if (status?.balance_url) {
      items.push({
        id: "monthly-drilldown",
        label: tableHeaderTerm(menuTerms, "Monthly drilldown"),
        onClick: () => openView("monthly"),
      });
    }
    const onMatrix =
      activeYear &&
      !termsView &&
      !categoriesView &&
      !ipView &&
      !splitView &&
      !passwordView &&
      !journalView &&
      !afschrijvingenView &&
      !searchView;
    if (onMatrix) {
      items.push({
        id: "back-to-matrix",
        label: tableHeaderTerm(menuTerms, "Back to summary"),
        onClick: () => openView("main"),
      });
    }
    items.push({
        id: "small-expenses",
        label: tableHeaderTerm(menuTerms, "Smaller expenses"),
        disabled: scratchBusy || wipeBusy || crossBusy,
        onClick: () => {
          if (scratchBusy || wipeBusy || crossBusy) return;
          setWipeError(null);
          setSmallOpen("expense");
        },
      });
      items.push({
        id: "small-income",
        label: tableHeaderTerm(menuTerms, "Smaller income"),
        disabled: scratchBusy || wipeBusy || crossBusy,
        onClick: () => {
          if (scratchBusy || wipeBusy || crossBusy) return;
          setWipeError(null);
          setSmallOpen("income");
        },
      });
    if (access !== "local") {
      items.push({
        id: "wipe-year",
        label: wipeBusy ? "Wiping…" : tableHeaderTerm(menuTerms, "Wipe Year"),
        disabled: scratchBusy || wipeBusy || crossBusy,
        onClick: doWipeYear,
      });
    }
    items.push({
      id: "categories",
      label: tableHeaderTerm(menuTerms, "Edit categories"),
      onClick: () => openView("categories"),
    });
    items.push({
      id: "ip-access",
      label: tableHeaderTerm(menuTerms, "Restrict IP access"),
      onClick: () => openView("ip"),
    });
    items.push({
      id: "set-password",
      label: tableHeaderTerm(menuTerms, "Set password"),
      onClick: () => openView("password"),
    });
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
        label: tableHeaderTerm(menuTerms, "Log out"),
        onClick: requestLogout,
      });
    }
    return sortMenuItems(
      items.filter((item) =>
        menuItemAllowed(item.id, access, status?.menu_items, status?.administrator)
      )
    );
  }, [headerActions, uploadUrl, access, scratchBusy, wipeBusy, crossBusy, openingBusy, requestLogout, activeYear, bankView, termsView, categoriesView, ipView, splitView, passwordView, journalView, afschrijvingenView, searchView, status?.balance_url, status?.result_url, status?.menu_items, status?.administrator, menuTerms]);

  function runMenuItem(item: HeaderAction) {
    item.onClick?.();
  }

  return (
    <HeaderActionsContext.Provider value={setHeaderActions}>
    <NoteRescoreQueuedContext.Provider value={noteRescoreQueued}>
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
            {!termsView && !categoriesView && !ipView && !splitView && !passwordView && !journalView && !afschrijvingenView && !searchView && activeYear ? (
              <YearSwitcher
                year={activeYear}
                years={yearOptions}
                onSelect={(y) => {
                  setActiveYear(y);
                  onCenterChanged?.();
                }}
              />
            ) : null}
            {showBankSwitcher && !termsView && !categoriesView && !ipView && !splitView && !passwordView && !journalView && !afschrijvingenView && !searchView ? (
              <BankSwitcher
                view={bankView}
                accounts={bankOptions}
                terms={menuTerms}
                onSelect={(v) => {
                  setBankView(v);
                  onCenterChanged?.();
                }}
              />
            ) : null}
            {!passwordView ? (
              <ActionsMenu items={menuItems} onPick={runMenuItem} />
            ) : null}
            {!passwordView ? <HelpQuestion terms={menuTerms} /> : null}
            {rescoreError ? <span> · {rescoreError}</span> : null}
            {switching ? <span className="center-switcher-busy">switching…</span> : null}
            {scratchError ? <span> · {scratchError}</span> : null}
            {wipeError ? <span> · {wipeError}</span> : null}
            {recalcOpen ? (
              <RecalcChoices
                terms={menuTerms}
                onCancel={() => setRecalcOpen(false)}
                onScratch={() => doRecalculate("scratch")}
                onIncremental={() => doRecalculate("incremental")}
              />
            ) : null}
            {wipeOpen ? (
              <WipeChoices
                terms={menuTerms}
                onCancel={() => setWipeOpen(false)}
                onRun={runWipe}
              />
            ) : null}
            {smallOpen ? (
              <SmallExpenses
                terms={menuTerms}
                onCancel={() => setSmallOpen(null)}
                onApply={(maximum, categoryId) => {
                  const income = smallOpen === "income";
                  setSmallOpen(null);
                  const extra: { person?: string; account?: string } = {};
                  if (access === "unit") {
                    extra.account = (status?.account || bankView || "").trim();
                  } else if (access === "personal" && bankView && bankView !== "consolidated") {
                    extra.account = bankView;
                  }
                  beginRefreshBusy("please wait... wiping");
                  flushSync(() => {
                    setWipeBusy(true);
                    setWipeError(null);
                  });
                  afterPaint(() => {
                    smallExpenses({ maximum, category_id: categoryId, income, ...extra })
                      .then(() => {
                        onCenterChanged?.();
                      })
                      .catch((e: Error) => setWipeError(e.message))
                      .finally(() => {
                        setWipeBusy(false);
                        endRefreshBusy();
                      });
                  });
                }}
              />
            ) : null}
            {status?.error ? (
              <span>
                {" · "}
                {/timed out/i.test(status.error)
                  ? "processing..."
                  : `sync error: ${status.error}`}
              </span>
            ) : null}
          </div>
          <div className="sync-notify-row">
            {notes.map((n) => (
              <button key={`${n.file_path}-${n.expires_at}`} type="button" className="sync-notify-btn">
                {n.file_path}
              </button>
            ))}
          </div>
          <LoggedInUsers names={status?.logged_in_usernames ?? []} />
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
      {children(brandName, activeYear, bankView, dataRev, banksState, bankOptions, menuTerms)}
    </div>
    </NoteRescoreQueuedContext.Provider>
    </HeaderActionsContext.Provider>
  );
}

function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

const WIPE_ITEMS: { key: keyof WipeFlags; en: string; nl: string }[] = [
  { key: "afschrijvingen", en: "Wipe automatic journal entries", nl: "Wis automatische journaalposten" },
  { key: "journal", en: "Wipe manual journal entries", nl: "Wis handmatige journaalposten" },
  { key: "statements", en: "Wipe bank statements", nl: "Wis bankafschriften" },
  {
    key: "categories_open",
    en: "Wipe categorization where modification < 2",
    nl: "Wis categorisatie voor modification < 2",
  },
  {
    key: "categories_cross",
    en: "Wipe categorization of cross-postings and current accounts",
    nl: "Wis categorisatie voor kruisposten en rekening courant",
  },
  { key: "categories_all", en: "Wipe all categorization", nl: "Wis alle categorisatie" },
  { key: "terms_general", en: "Wipe general terms", nl: "Wis G-termen" },
  { key: "terms_personal", en: "Wipe personal terms", nl: "Wis P-termen" },
  {
    key: "modification_open",
    en: "Set every modification below 2 to -1 and clear hits",
    nl: "Zet alle modification < 2 op -1 & wis hits",
  },
  {
    key: "modification_all",
    en: "Set every modification to -1 and clear hits",
    nl: "Zet alle modification op -1 & wis hits",
  },
];

type WipeFlags = {
  statements: boolean;
  journal: boolean;
  afschrijvingen: boolean;
  categories_open: boolean;
  categories_cross: boolean;
  categories_all: boolean;
  terms_general: boolean;
  terms_personal: boolean;
  modification_open: boolean;
  modification_all: boolean;
};

function emptyWipeFlags(): WipeFlags {
  return {
    statements: false,
    journal: false,
    afschrijvingen: false,
    categories_open: false,
    categories_cross: false,
    categories_all: false,
    terms_general: false,
    terms_personal: false,
    modification_open: false,
    modification_all: false,
  };
}

function RecalcChoices({
  terms,
  onCancel,
  onScratch,
  onIncremental,
}: {
  terms: Record<string, string> | undefined;
  onCancel: () => void;
  onScratch: () => void;
  onIncremental: () => void;
}) {
  return (
    <div className="priority-rules-overlay" onClick={onCancel}>
      <div
        className="priority-rules-dialog wipe-choices"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="wipe-choice-actions">
          <button type="button" className="priority-rules-close" onClick={onScratch}>
            {tableHeaderTerm(terms, "From scratch")}
          </button>
          <button type="button" className="priority-rules-close" onClick={onIncremental}>
            {tableHeaderTerm(terms, "Incremental")}
          </button>
          <button type="button" className="priority-rules-close" onClick={onCancel}>
            {tableHeaderTerm(terms, "Cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}

function WipeChoices({
  terms,
  onCancel,
  onRun,
}: {
  terms: Record<string, string> | undefined;
  onCancel: () => void;
  onRun: (choices: WipeFlags) => void;
}) {
  const [flags, setFlags] = useState<WipeFlags>(emptyWipeFlags);
  const anyChecked = WIPE_ITEMS.some((item) => flags[item.key]);
  const dutch = uiIsDutch(terms);
  return (
    <div className="priority-rules-overlay" onClick={onCancel}>
      <div
        className="priority-rules-dialog wipe-choices"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        {WIPE_ITEMS.map((item) => (
          <label className="wipe-choice" key={item.key}>
            <input
              type="checkbox"
              checked={flags[item.key]}
              onChange={(e) =>
                setFlags((prev) => ({ ...prev, [item.key]: e.target.checked }))
              }
            />
            {wipeItemLabel(terms, item, dutch)}
          </label>
        ))}
        <div className="wipe-choice-actions">
          <button
            type="button"
            className="priority-rules-close"
            disabled={!anyChecked}
            onClick={() => onRun(flags)}
          >
            OK
          </button>
          <button type="button" className="priority-rules-close" onClick={onCancel}>
            {tableHeaderTerm(terms, "Cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}

function SmallExpenses({
  terms,
  onCancel,
  onApply,
}: {
  terms: Record<string, string> | undefined;
  onCancel: () => void;
  onApply: (maximum: string, categoryId: number) => void;
}) {
  const [maximum, setMaximum] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [categories, setCategories] = useState<CatalogCategory[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  useEffect(() => {
    let gone = false;
    getCatalog()
      .then((res) => {
        if (gone) return;
        setCategories(res.categories.filter((row) => !row.is_remainder && row.category_id != null));
      })
      .catch((e: Error) => {
        if (!gone) setLoadError(e.message);
      });
    return () => {
      gone = true;
    };
  }, []);
  const amount = maximum.trim().replace(",", ".");
  const parsed = Number(amount);
  const ready = amount !== "" && Number.isFinite(parsed) && parsed > 0 && categoryId !== "";
  return (
    <div className="priority-rules-overlay" onClick={onCancel}>
      <div
        className="priority-rules-dialog wipe-choices"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <label className="wipe-choice small-expense-field">
          {tableHeaderTerm(terms, "Maximum amount")}
          <input
            type="text"
            inputMode="decimal"
            value={maximum}
            onChange={(e) => setMaximum(e.target.value)}
          />
        </label>
        <label className="wipe-choice small-expense-field">
          {tableHeaderTerm(terms, "category")}
          <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
            <option value="" />
            {categories.map((row) => (
              <option key={row.category_id} value={String(row.category_id)}>
                {row.local_code} {row.label}
              </option>
            ))}
          </select>
        </label>
        {loadError ? <p>{loadError}</p> : null}
        <div className="wipe-choice-actions">
          <button
            type="button"
            className="priority-rules-close"
            disabled={!ready}
            onClick={() => onApply(amount, Number(categoryId))}
          >
            {tableHeaderTerm(terms, "Apply")}
          </button>
          <button type="button" className="priority-rules-close" onClick={onCancel}>
            {tableHeaderTerm(terms, "Cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}

function tableHeaderTerm(
  terms: Record<string, string> | undefined,
  key: string
): string {
  const label = terms?.[key]?.trim();
  return label || key;
}

function wipeItemLabel(
  terms: Record<string, string> | undefined,
  item: { en: string; nl: string },
  dutch: boolean
): string {
  const label = terms?.[item.en]?.trim();
  if (label && label !== item.en) return label;
  return dutch ? item.nl : item.en;
}

function RichLabel({ text }: { text: string }) {
  if (!text.includes("<")) return text;
  return <span dangerouslySetInnerHTML={{ __html: text }} />;
}

function uiIsDutch(terms?: Record<string, string>): boolean {
  return (
    tableHeaderTerm(terms, "Log out") === "Uitloggen" ||
    tableHeaderTerm(terms, "Download transactions") === "Uitlezen bankafschriften"
  );
}

function ytdConsentHint(terms?: Record<string, string>): string {
  return uiIsDutch(terms)
    ? "Gebruik achtereenvolgens 'Verwijder toestemming', 'Bereid toestemming', en tenslotte opnieuw 'YTD bankafschriften'"
    : "Use sequentially 'Invalidate consent',  'Prepare consent', and 'Download YTD'";
}

type RabobankSaveFile = {
  person: string;
  filename: string;
  text: string;
};

function rabobankFilename(
  person: string,
  dateFrom: string,
  dateTo: string,
  ytd: boolean
): string {
  const safe = person.replace(/[^\w.-]+/g, "_") || "rabobank";
  if (ytd) {
    const year = dateFrom.slice(0, 4) || String(new Date().getFullYear());
    return `rabobank-ytd-${safe}-${year}.json`;
  }
  return `rabobank-${safe}-${dateFrom || "from"}-${dateTo || "to"}.json`;
}

function rabobankFilesFrom(
  results: RefreshPersonResult[] | undefined,
  ytd: boolean
): RabobankSaveFile[] {
  const files: RabobankSaveFile[] = [];
  for (const row of results || []) {
    const doc: RabobankExport | undefined = row.rabobank_export;
    if (!doc) continue;
    const person = (row.person_name || doc.person || "rabobank").trim() || "rabobank";
    const dateFrom = doc.date_from || row.date_from || "";
    const dateTo = doc.date_to || row.date_to || "";
    files.push({
      person,
      filename: rabobankFilename(person, dateFrom, dateTo, ytd),
      text: JSON.stringify(doc, null, 2),
    });
  }
  return files;
}

function stripRabobankExport(results: RefreshPersonResult[]): RefreshPersonResult[] {
  return results.map((row) => {
    if (!row.rabobank_export) return row;
    const rest = { ...row };
    delete rest.rabobank_export;
    return rest;
  });
}

async function writeLocalFile(filename: string, text: string): Promise<void> {
  const picker = (
    window as Window & {
      showSaveFilePicker?: (options: {
        suggestedName?: string;
        types?: { description?: string; accept: Record<string, string[]> }[];
      }) => Promise<{
        createWritable: () => Promise<{
          write: (data: string) => Promise<void>;
          close: () => Promise<void>;
        }>;
      }>;
    }
  ).showSaveFilePicker;
  if (typeof picker === "function") {
    const handle = await picker({
      suggestedName: filename,
      types: [{ description: "JSON", accept: { "application/json": [".json"] } }],
    });
    const writable = await handle.createWritable();
    await writable.write(text);
    await writable.close();
    return;
  }
  const blob = new Blob([text], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function RabobankSaveDialog({
  files,
  terms,
  onDismiss,
  onSaved,
}: {
  files: RabobankSaveFile[];
  terms: Record<string, string> | undefined;
  onDismiss: () => void;
  onSaved: (index: number) => void;
}) {
  const dutch = uiIsDutch(terms);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function saveAt(index: number) {
    const file = files[index];
    if (!file) return;
    setSaveError(null);
    try {
      await writeLocalFile(file.filename, file.text);
      onSaved(index);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setSaveError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="priority-rules-overlay">
      <div className="priority-rules-dialog wipe-choices" role="dialog" aria-modal="true">
        <p>
          {dutch
            ? "Rabobank-gegevens. Kies waar het bestand wordt opgeslagen. De gegevens worden niet in de database gezet."
            : "Rabobank data. Choose where to save the file. The data is not written to the database."}
        </p>
        {files.map((file, index) => (
          <div className="wipe-choice-actions" key={`${file.filename}:${index}`}>
            <span>{file.filename}</span>
            <button type="button" className="priority-rules-close" onClick={() => void saveAt(index)}>
              {dutch ? "Opslaan" : "Save"}
            </button>
          </div>
        ))}
        {saveError ? <p className="error">{saveError}</p> : null}
        <div className="wipe-choice-actions">
          <button type="button" className="priority-rules-close" onClick={onDismiss}>
            {tableHeaderTerm(terms, "Cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}

const COLUMN_HEADER_KEYS: Record<string, string> = {
  amount: "Amount",
  type: "Type",
  name: "Name",
  iban: "IBAN",
  description: "Description",
  date: "Date",
  category: "Category",
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
    view === "password" ||
    view === "journal" ||
    view === "afschrijvingen" ||
    view === "search" ||
    view === "monthly"
  ) {
    return view;
  }
  return "main";
}

function viewUrl(
  target:
    | "main"
    | "terms"
    | "categories"
    | "ip"
    | "password"
    | "journal"
    | "afschrijvingen"
    | "search"
    | "monthly"
): string {
  if (target === "terms") return `${window.location.pathname}?view=terms`;
  if (target === "categories") return `${window.location.pathname}?view=categories`;
  if (target === "ip") return `${window.location.pathname}?view=ip`;
  if (target === "password") return `${window.location.pathname}?view=password`;
  if (target === "journal") return `${window.location.pathname}?view=journal`;
  if (target === "afschrijvingen") return `${window.location.pathname}?view=afschrijvingen`;
  if (target === "search") return `${window.location.pathname}?view=search`;
  if (target === "monthly") return `${window.location.pathname}?view=monthly`;
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

function openView(
  target:
    | "main"
    | "terms"
    | "categories"
    | "ip"
    | "password"
    | "journal"
    | "afschrijvingen"
    | "search"
    | "monthly"
) {
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
  const isJournal = appView === "journal";
  const isAfschrijvingen = appView === "afschrijvingen";
  const isSearch = appView === "search";
  const isMonthly = appView === "monthly";
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

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      // Overlays that already handle Escape keep that behavior.
      const target = e.target as HTMLElement | null;
      if (target?.closest?.(".term-context-backdrop, .term-assign-overlay")) return;
      openView("main");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    function onMessage(e: MessageEvent) {
      if (e.data?.type === "agrolav-focus-front") {
        try {
          window.focus();
        } catch {
          // ignore
        }
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
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
      journalView={isJournal}
      afschrijvingenView={isAfschrijvingen}
      searchView={isSearch}
      onLogout={
        authRequired
          ? () => {
              closeBalanceSheetWindow();
              closeResultSheetWindow();
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
      {(brandName, year, bankView, dataRev, banks, bankOptions, menuTerms) =>
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
        ) : isJournal ? (
          <JournalEditor
            key={wsEpoch}
            year={Number(year)}
            terms={menuTerms}
            onBack={() => openView("main")}
          />
        ) : isAfschrijvingen ? (
          <AfschrijvingenEditor
            key={wsEpoch}
            terms={menuTerms}
            onBack={() => openView("main")}
          />
        ) : isSearch ? (
          <SearchStatementsApp key={wsEpoch} terms={menuTerms} />
        ) : isMonthly ? (
          <MonthlyDrilldownApp
            key={wsEpoch}
            brandName={brandName}
            year={year}
            bankView={bankView}
            dataRev={dataRev}
            bankOptions={bankOptions}
            menuTerms={menuTerms}
          />
        ) : (
          <MainApp
            key={wsEpoch}
            brandName={brandName}
            year={year}
            bankView={bankView}
            dataRev={dataRev}
            banks={banks}
            bankOptions={bankOptions}
            menuTerms={menuTerms}
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

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <h1 className="login-title">Expenses</h1>
        {otp ? (
          <>
            <p className="login-muted">Enter the code from your authenticator app.</p>
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

function accountSidebarTitle(
  brandName: string,
  bankView: string,
  bankOptions: BankAccount[] | undefined,
  terms: Record<string, string> | undefined
): string {
  const title = brandName;
  const accountCount = bankOptions?.length ?? 0;
  if (accountCount <= 1) return title;
  const subtitle =
    bankView === "consolidated"
      ? tableHeaderTerm(terms, "Consolidated")
      : bankOptions?.find((a) => a.iban === bankView)?.account_name?.trim() || "";
  if (!subtitle) return title;
  return `${title}\n${subtitle}`;
}

function FitSidebarTitle({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <h1 className="app-heading">
      {lines.map((line, i) => (
        <span key={i} className={i > 0 ? "app-heading-sub" : undefined}>
          {i > 0 ? <br /> : null}
          {line}
        </span>
      ))}
    </h1>
  );
}

function DownloadAccountList({ status }: { status: StoredRefreshStatus | null }) {
  const results = status?.results ?? [];
  const groups = results.filter((r) => (r.accounts?.length ?? 0) > 0);
  const notes = results.filter((r) => (r.accounts?.length ?? 0) === 0 && (r.skipped || r.reason));
  const warnings = status?.warnings ?? [];
  if (!groups.length && !notes.length && !warnings.length) return null;
  const showPerson = groups.length > 1 || notes.length > 0;
  return (
    <ul className="download-accounts">
      {groups.flatMap((r) =>
        (r.accounts ?? []).map((account, index) => {
          const iban = (account.iban || "").trim();
          const name = (account.name || "").trim();
          return (
            <li key={`${r.person_name}:${iban || name}:${index}`}>
              <span className="download-account-label">
                {showPerson ? <span className="download-account-name">{r.person_name}</span> : null}
                <span className="download-account-iban">{iban || name}</span>
                {iban && name ? <span className="download-account-name">{name}</span> : null}
              </span>
              <span className="download-account-count">{account.inserted}</span>
            </li>
          );
        })
      )}
      {notes.map((r) => (
        <li key={`note:${r.person_name}:${r.reason || ""}`}>
          <span className="download-account-label">
            <span className="download-account-iban">{r.person_name}</span>
            {r.reason ? <span className="download-account-name">{r.reason}</span> : null}
          </span>
        </li>
      ))}
      {warnings.map((warning, index) => (
        <li key={`warn:${index}`}>
          <span className="download-account-name">{warning}</span>
        </li>
      ))}
    </ul>
  );
}

function MainApp({
  brandName,
  year,
  bankView,
  dataRev,
  bankOptions,
  menuTerms,
}: {
  brandName: string;
  year: string;
  bankView: string;
  dataRev: number;
  banks?: BanksFlags;
  bankOptions?: BankAccount[];
  menuTerms?: Record<string, string>;
}) {
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null);
  const [selection, setSelection] = useState<CellSelection | null>(null);
  const [detail, setDetail] = useState<TransactionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [wipeOpen, setWipeOpen] = useState(false);
  const [wipePerson, setWipePerson] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [firstDownloading, setFirstDownloading] = useState(false);
  const [rabobankFiles, setRabobankFiles] = useState<RabobankSaveFile[] | null>(null);
  const [refreshScope, setRefreshScope] = useState<RefreshStatusScope | null>(null);
  const [refreshStatus, setRefreshStatus] = useState<StoredRefreshStatus | null>(null);
  const [hasSecrets, setHasSecrets] = useState(false);
  const [addPersonUrl, setAddPersonUrl] = useState<string | null>(null);
  const [termMenu, setTermMenu] = useState<{
    term: string;
    x: number;
    y: number;
    transactionId: string;
  } | null>(null);
  const [termMenuSettings, setTermMenuSettings] = useState<SettingsResponse | null>(null);
  const termSettingsRef = useRef<SettingsResponse | null>(null);
  const [loginPerson, setLoginPerson] = useState("");
  const [loginAccess, setLoginAccess] = useState("");
  const [loginUsername, setLoginUsername] = useState("");
  const [languageLong, setLanguageLong] = useState<Record<string, string>>({});
  const selectionRef = useRef<CellSelection | null>(null);
  const dirtyRef = useRef(false);
  const viewInitRef = useRef(false);

  useEffect(() => {
    getCentraleStatus()
      .then((s) => {
        setHasSecrets(Boolean(s.has_secrets));
        const scoped = Boolean((s.person || "").trim());
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
        setLoginPerson(person);
        setLoginAccess((s.access || "").trim());
        setLoginUsername((s.username || "").trim());
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
        setAddPersonUrl(null);
      });
  }, []);

  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((s) => {
        if (cancelled) return;
        termSettingsRef.current = s;
        setLanguageLong(s.language_long ?? {});
      })
      .catch(() => {
        if (!cancelled) setLanguageLong({});
      });
    return () => {
      cancelled = true;
    };
  }, [dataRev]);

  useEffect(() => {
    selectionRef.current = selection;
  }, [selection]);

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
      const prior = Number(existing?.modification);
      const priorFlag = Number.isFinite(prior) ? prior : -1;
      const categoryClick = !descriptionChanged && Number(modified.modification) === 2;
      if (categoryChanged && currentCode != null && nextCode !== currentCode) {
        return patchDetail(prev, { removeId: id });
      }
      if (descriptionChanged) {
        return patchDetail(prev, {
          update: { ...modified, modification: handModification(priorFlag, "description") },
        });
      }
      if (categoryChanged || categoryClick) {
        return patchDetail(prev, {
          update: { ...modified, modification: handModification(priorFlag, "category") },
        });
      }
      return prev;
    });
    recordModification(selection.person_name, modified)
      .then(() => getMatrix(year, bankQuery))
      .then(setMatrix)
      .catch((e: Error) => setError(e.message));
  }

  function openTermMenu(e: MouseEvent, cellText: string, transactionId: string) {
    e.preventDefault();
    e.stopPropagation();
    setError(null);
    const word = wordAtClick(e.currentTarget, e.clientX, e.clientY) || cellText.trim();
    if (!word) return;
    const open = { term: word, x: e.clientX, y: e.clientY, transactionId };
    const cached = termSettingsRef.current;
    if (cached) {
      setTermMenuSettings(cached);
      setTermMenu(open);
      return;
    }
    getSettings()
      .then((settings) => {
        termSettingsRef.current = settings;
        setTermMenuSettings(settings);
        setTermMenu(open);
      })
      .catch((err: Error) => setError(err.message));
  }

  function closeTermMenu() {
    setTermMenu(null);
    setTermMenuSettings(null);
  }

  function saveTermMenu(
    term: string,
    targetCategory: string,
    general: boolean,
    account?: string,
    transactionId?: string
  ) {
    handsetDebug("saveTermMenu", { term, targetCategory, general, account, transactionId });
    const centerTarget = centerNameFromKey(account || "");
    if (centerTarget) {
      const sel = selectionRef.current;
      const rowId = transactionId || termMenu?.transactionId;
      closeTermMenu();
      if (sel && targetCategory !== sel.category) {
        setDetail((prev) =>
          prev ? { ...prev, transactions: prev.transactions.filter((row) => !bookingLeavesCategory(row, term, rowId)) } : prev
        );
      }
      termSettingsRef.current = null;
      return updateCenterAccountTerms({
        category: targetCategory,
        add: [term],
        remove: [],
        center: centerTarget,
      })
        .catch((err: Error) => {
          setError(err.message);
          if (sel) return loadDetail(sel.person_name, sel.category, { quiet: true });
        })
        .then(() => undefined);
    }
    const person_name = selectionRef.current?.person_name;
    if (!general && !person_name) return Promise.resolve();
    const sel = selectionRef.current;
    const rowId = transactionId || termMenu?.transactionId;
    closeTermMenu();
    if (sel && targetCategory !== sel.category) {
      setDetail((prev) =>
        prev ? { ...prev, transactions: prev.transactions.filter((row) => !bookingLeavesCategory(row, term, rowId)) } : prev
      );
    }
    return addCategoryTerm({
      category_name: targetCategory,
      term,
      general,
      person: general ? undefined : person_name,
      account: general ? undefined : account,
    })
      .then((res) => {
        if (res.matrix) setMatrix(res.matrix);
      })
      .catch((err: Error) => {
        setError(err.message);
        if (sel) return loadDetail(sel.person_name, sel.category, { quiet: true });
      });
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

  function finishBankDownload(
    res: { matrix?: MatrixResponse; results?: RefreshPersonResult[]; warnings?: string[] },
    ytd: boolean
  ) {
    const files = rabobankFilesFrom(res.results, ytd);
    const results = stripRabobankExport(res.results || []);
    if (res.matrix) setMatrix(res.matrix);
    const payload: StoredRefreshStatus = {
      results,
      warnings: res.warnings || [],
    };
    saveStoredRefreshStatus(payload, refreshScope);
    setRefreshStatus(payload);
    setSelection(null);
    setDetail(null);
    if (files.length) setRabobankFiles(files);
  }

  function doRefresh() {
    if (refreshing) return;
    beginRefreshBusy();
    flushSync(() => {
      setRefreshing(true);
      setError(null);
      setRefreshStatus(null);
    });
    clearStoredRefreshStatus(refreshScope);
    afterPaint(() => {
      refreshAll()
        .then((res) => {
          finishBankDownload(res, false);
        })
        .catch((e: Error) => setError(e.message))
        .finally(() => {
          setRefreshing(false);
          endRefreshBusy();
        });
    });
  }

  const termsForUi = matrix?.table_header_terms ?? menuTerms;

  function pickManagedPerson(): string | null {
    const selected = (selection?.person_name || "").trim();
    const names = (matrix?.people || [])
      .map((p) => (p.person_name || "").trim())
      .filter(Boolean);
    if (selected && names.includes(selected)) return selected;
    if (names.length === 1) return names[0];
    const dutch = uiIsDutch(termsForUi);
    const hint = names.length ? ` (${names.join(", ")})` : "";
    const raw = window.prompt(
      dutch ? `Persoon${hint}` : `Person${hint}`,
      selected || names[0] || ""
    );
    if (raw == null) return null;
    return raw.trim() || null;
  }

  function ytdNotAllowed(
    res: { results?: RefreshPersonResult[]; warnings?: string[] },
    start: string
  ): boolean {
    for (const r of res.results || []) {
      if (r.skipped && r.reason === "needs_consent_renewal") return true;
      if (r.date_from && r.date_from > start) return true;
    }
    return (res.warnings || []).some((w) =>
      /raised to|renew consent|only the last/i.test(w)
    );
  }

  function doYtdDownload() {
    if (refreshing || firstDownloading) return;
    const person_name = pickManagedPerson();
    if (!person_name) return;
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
          finishBankDownload(res, true);
          if (ytdNotAllowed(res, start)) {
            window.alert(ytdConsentHint(termsForUi));
          }
        })
        .catch((e: Error) => setError(e.message))
        .finally(() => {
          setFirstDownloading(false);
          endRefreshBusy();
        });
    });
  }

  function doWipePersonYear() {
    if (refreshing) return;
    const person_name = pickManagedPerson();
    if (!person_name) return;
    setError(null);
    setWipePerson(person_name);
    setWipeOpen(true);
  }

  function runWipePerson(choices: WipeFlags) {
    const person_name = wipePerson;
    setWipeOpen(false);
    if (!person_name) return;
    beginRefreshBusy();
    flushSync(() => {
      setRefreshing(true);
      setError(null);
    });
    afterPaint(() => {
      wipeYear({ ...choices, person: person_name })
        .then(() => loadMatrixOnly())
        .catch((e: Error) => setError(e.message))
        .finally(() => {
          setRefreshing(false);
          endRefreshBusy();
        });
    });
  }

  function doPrepareConsent() {
    const person_name = pickManagedPerson();
    if (!person_name) return;
    setError(null);
    prepareConsent(person_name)
      .then((res) => {
        const url = (res.authorization_url || "").trim();
        if (!url) {
          setError("No authorization URL");
          return;
        }
        window.location.assign(url);
      })
      .catch((e: Error) => setError(e.message));
  }

  function doInvalidateConsent() {
    const person_name = pickManagedPerson();
    if (!person_name) return;
    const dutch = uiIsDutch(termsForUi);
    const ok = window.confirm(
      dutch
        ? `Toestemming voor ${person_name} verwijderen?`
        : `Invalidate consent for ${person_name}?`
    );
    if (!ok) return;
    setError(null);
    invalidateConsent(person_name).catch((e: Error) => setError(e.message));
  }

  const setHeaderActions = useContext(HeaderActionsContext);
  useEffect(() => {
    const items: HeaderAction[] = [];
    if (hasSecrets) {
      items.push({
        id: "refresh",
        label: refreshing
          ? "Downloading…"
          : tableHeaderTerm(matrix?.table_header_terms, "Download transactions"),
        disabled: refreshing || firstDownloading,
        onClick: doRefresh,
      });
      items.push({
        id: "prepare-consent",
        label: tableHeaderTerm(termsForUi, "Prepare consent"),
        disabled: refreshing || firstDownloading,
        onClick: doPrepareConsent,
      });
      items.push({
        id: "invalidate-consent",
        label: tableHeaderTerm(termsForUi, "Invalidate consent"),
        disabled: refreshing || firstDownloading,
        onClick: doInvalidateConsent,
      });
      items.push({
        id: "download-ytd",
        label: firstDownloading
          ? "Downloading…"
          : tableHeaderTerm(termsForUi, "Download YTD"),
        disabled: refreshing || firstDownloading,
        onClick: doYtdDownload,
      });
    }
    if (loginAccess === "local") {
      items.push({
        id: "wipe-year",
        label: tableHeaderTerm(termsForUi, "Wipe Year"),
        disabled: refreshing || firstDownloading,
        onClick: doWipePersonYear,
      });
    }
    if (addPersonUrl) {
      items.push({
        id: "add-person",
        label: tableHeaderTerm(matrix?.table_header_terms, "Add person"),
        onClick: () => window.location.assign(addPersonUrl),
      });
    }
    setHeaderActions(items);
    return () => setHeaderActions([]);
  }, [
    hasSecrets,
    refreshing,
    firstDownloading,
    addPersonUrl,
    loginAccess,
    setHeaderActions,
    matrix,
    menuTerms,
    selection,
  ]);

  const inPView = selection !== null;
  const displayMatrix = matrix;
  const columnLabel = (name: string) =>
    loginAccess === "unit" && loginUsername ? loginUsername : name;

  const sidebarTitle = accountSidebarTitle(
    brandName,
    bankView,
    bankOptions,
    matrix?.table_header_terms ?? menuTerms
  );

  return (
    <div className="app">
      <aside className="sidebar">
        {sidebarTitle ? <FitSidebarTitle text={sidebarTitle} /> : null}
        <DownloadAccountList status={refreshStatus} />

        {inPView && displayMatrix && (
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
              matrix={displayMatrix}
              person_name={selection.person_name}
              selectedCategory={selection.category}
              omitEmpty={
                loginAccess === "local" ||
                loginAccess === "personal" ||
                loginAccess === "unit"
              }
              columnLabel={columnLabel}
              onPick={(category) => selectCell(selection.person_name, category)}
              onPersonChange={(person_name) => selectCell(person_name, selection.category)}
            />
          </>
        )}
      </aside>

      <main className="content">
        {error && <p className="error">{error}</p>}
        {wipeOpen ? (
          <WipeChoices
            terms={termsForUi}
            onCancel={() => setWipeOpen(false)}
            onRun={runWipePerson}
          />
        ) : null}
        {rabobankFiles?.length ? (
          <RabobankSaveDialog
            files={rabobankFiles}
            terms={termsForUi}
            onDismiss={() => setRabobankFiles(null)}
            onSaved={(index) =>
              setRabobankFiles((prev) => {
                if (!prev) return prev;
                const next = prev.filter((_, item) => item !== index);
                return next.length ? next : null;
              })
            }
          />
        ) : null}
        {!inPView && !matrix && !error && <p>Loading…</p>}
        {!inPView && displayMatrix && (
          <>
            <MatrixTable
              matrix={displayMatrix}
              selection={selection}
              omitEmpty={
                loginAccess === "local" ||
                loginAccess === "personal" ||
                loginAccess === "unit"
              }
              columnLabel={columnLabel}
              onPick={selectCell}
            />
          </>
        )}
        {inPView && !detail && !error && <p>Loading…</p>}
        {inPView && detail && (
          <PTable
            categoryName={selection.category}
            detail={detail}
            year={year}
            bank={bankQuery}
            languageLong={languageLong}
            onModify={modifyTransaction}
            onCategoryError={setError}
            onTermContextMenu={openTermMenu}
          />
        )}
        {termMenu && termMenuSettings && (
          <TermContextMenu
            settings={termMenuSettings}
            initialTerm={termMenu.term}
            personScope={loginPerson}
            showCenters={!loginPerson && (loginAccess === "local" || loginAccess === "country")}
            generalEditable={loginAccess.trim().toLowerCase() === "country"}
            bankIban={bankView !== "consolidated" ? bankView : undefined}
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
  const [priorityOpen, setPriorityOpen] = useState(false);
  const [personScope, setPersonScope] = useState("");
  const [centerName, setCenterName] = useState("");
  const [generalEditable, setGeneralEditable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const channelRef = useRef<BroadcastChannel | null>(null);

  useEffect(() => {
    let cancelled = false;
    function load() {
      Promise.all([getSettings(), getCentraleStatus().catch(() => null)])
        .then(([data, status]) => {
          if (cancelled) return;
          setSettings(data);
          setPersonScope((status?.person || "").trim());
          setCenterName((status?.center || "").trim());
          setGeneralEditable((status?.access || "").trim().toLowerCase() === "country");
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

  function patchSettings(
    prev: SettingsResponse,
    group: string,
    category: string,
    terms: string[]
  ): SettingsResponse {
    if (group === "general") {
      return { ...prev, general: { ...prev.general, [category]: terms } };
    }
    if ((prev.account_groups ?? []).some((g) => g.account_key === group)) {
      return {
        ...prev,
        account_groups: (prev.account_groups ?? []).map((g) =>
          g.account_key === group
            ? { ...g, categories: patchCategories(g.categories, category, terms) }
            : g
        ),
      };
    }
    const personGroup = { ...(prev.personal[group] ?? {}) };
    if (terms.length) personGroup[category] = terms;
    else delete personGroup[category];
    return { ...prev, personal: { ...prev.personal, [group]: personGroup } };
  }

  function updateTerms(group: string, category: string, terms: string[]) {
    updateTermsMany([{ group, category, terms }]);
  }

  function updateTermsMany(
    items: { group: string; category: string; terms: string[] }[]
  ) {
    if (!items.length) return;
    setSettings((prev) =>
      items.reduce(
        (acc, item) =>
          acc ? patchSettings(acc, item.group, item.category, item.terms) : acc,
        prev
      )
    );
    Promise.all(
      items.map((item) => updateSettings(item.group, item.category, item.terms))
    )
      .then((results) => {
        setSettings((prev) =>
          results.reduce(
            (acc, res, i) =>
              acc
                ? patchSettings(
                    acc,
                    items[i].group,
                    items[i].category,
                    res.terms ?? items[i].terms
                  )
                : acc,
            prev
          )
        );
        channelRef.current?.postMessage("recalculated");
      })
      .catch((e: Error) => setError(e.message));
  }

  function applyCenterAccountTerms(
    category: string,
    add: string[],
    remove: string[],
    center?: string
  ) {
    const target = (center || "").trim();
    const targetKey = target.toLowerCase();
    setSettings((prev) => {
      if (!prev) return prev;
      const tagged = (prev.account_groups || []).some((group) => (group.center || "").trim());
      return {
        ...prev,
        account_groups: (prev.account_groups || []).map((group) => {
          const groupCenter = (group.center || "").trim().toLowerCase();
          if (targetKey && tagged && groupCenter !== targetKey) return group;
          const current = group.categories[category] ?? [];
          const next = [
            ...current.filter((term) => !remove.includes(term)),
            ...add.filter((term) => !current.includes(term)),
          ];
          return {
            ...group,
            categories: {
              ...group.categories,
              [category]: sortTerms(next),
            },
          };
        }),
      };
    });
    updateCenterAccountTerms({ category, add, remove, center: target || undefined })
      .then(() => {
        channelRef.current?.postMessage("recalculated");
        return getSettings();
      })
      .then((data) => setSettings(data))
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
        <div
          className="win-hint lang-html"
          dangerouslySetInnerHTML={{ __html: settings?.language_long?.["term window hint"] ?? "" }}
        />
        <button
          type="button"
          className="sidebar-knob info-knob"
          onClick={() => setPriorityOpen(true)}
        >
          {tableHeaderTerm(settings?.table_header_terms, "Priority rules")}
        </button>
      </aside>
      {priorityOpen ? (
        <PriorityRulesDialog
          title={tableHeaderTerm(settings?.table_header_terms, "Priority rules")}
          body={settings?.language_long?.["priority rules"] ?? ""}
          closeLabel={tableHeaderTerm(settings?.table_header_terms, "Close")}
          onClose={() => setPriorityOpen(false)}
        />
      ) : null}
      <main className="content terms-content">
        {error && <p className="error">{error}</p>}
        {settings ? (
          <TermsTables
            settings={settings}
            personScope={personScope}
            centerName={centerName}
            generalEditable={generalEditable}
            onUpdate={updateTerms}
            onUpdateMany={updateTermsMany}
            onUpdateCenter={applyCenterAccountTerms}
          />
        ) : (
          <p>Loading…</p>
        )}
      </main>
    </div>
  );
}

type CatalogDraft = {
  key: string;
  category_id: string;
  local_code: string;
  label: string;
  is_remainder: boolean;
};

function catalogDraftConflict(rows: CatalogDraft[]): string | null {
  const ids = new Set<number>();
  const codes = new Set<number>();
  for (const row of rows) {
    const id = Number.parseInt(row.category_id, 10);
    const code = Number.parseInt(row.local_code, 10);
    if (!Number.isFinite(id) || id < 1) {
      return "Each category needs a numeric id";
    }
    if (!Number.isFinite(code) || code < 1) {
      return "Each category needs a numeric code";
    }
    if (ids.has(id)) {
      return `Category id ${id} is already in use`;
    }
    if (codes.has(code)) {
      return `Category code ${code} is already in use`;
    }
    ids.add(id);
    codes.add(code);
  }
  return null;
}

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
    category_id: row.category_id != null ? String(row.category_id) : "",
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
          category_id: "",
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
    setSaved(false);
    const conflict = catalogDraftConflict(draft);
    if (conflict) {
      setError(`Please review your submission: ${conflict}`);
      return;
    }
    setBusy(true);
    const payload: CatalogCategory[] = draft.map((row) => ({
      category_id: Number.parseInt(row.category_id, 10),
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
          Category window for {country || "this country"}. Code and id must
          both be unused when you add a category. Changing a label keeps
          bookings on that category. Deleting a category moves leftover
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
                  <th>Id</th>
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
                        className="catalog-id"
                        inputMode="numeric"
                        value={row.category_id}
                        onChange={(e) => patchRow(row.key, { category_id: e.target.value })}
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

function plainHubError(raw: string): string {
  return reviewSubmissionMessage(raw).replace(/^Please review your submission:\s*/, "");
}

function SetPasswordApp() {
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [totp, setTotp] = useState<TotpStatus | null>(null);
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [code, setCode] = useState("");
  const [totpError, setTotpError] = useState<string | null>(null);
  const [totpOk, setTotpOk] = useState<string | null>(null);
  const [totpBusy, setTotpBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getTotpStatus()
      .then((row) => {
        if (!cancelled) setTotp(row);
      })
      .catch((err: Error) => {
        if (!cancelled) setTotpError(plainHubError(err.message));
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
    const newPassword = next.trim();
    const again = confirm.trim();
    if (!newPassword && !again) {
      setOk("Password unchanged.");
      return;
    }
    if (!newPassword || !again) {
      setError("Enter the new password in both fields, or leave both blank.");
      return;
    }
    setBusy(true);
    setPersonPassword({
      new_password: newPassword,
      confirm: again,
    })
      .then(() => {
        setOk("Password saved.");
        setNext("");
        setConfirm("");
      })
      .catch((err: Error) => setError(reviewSubmissionMessage(err.message)))
      .finally(() => setBusy(false));
  }

  function beginSetup() {
    setTotpError(null);
    setTotpOk(null);
    setTotpBusy(true);
    startTotp()
      .then((row) => {
        setSetup(row);
        setCode("");
      })
      .catch((err: Error) => setTotpError(plainHubError(err.message)))
      .finally(() => setTotpBusy(false));
  }

  function confirmSetup(e: FormEvent) {
    e.preventDefault();
    if (!setup) return;
    setTotpError(null);
    setTotpOk(null);
    setTotpBusy(true);
    confirmTotp({ enroll_token: setup.enroll_token, code: code.trim() })
      .then(() => getTotpStatus())
      .then((row) => {
        setSetup(null);
        setCode("");
        setTotp(row);
        if (!row.enrolled) {
          setTotpError("The code matched but the secret is not stored. Set it up again.");
          return;
        }
        setTotpOk("Authenticator is on. The next sign-in asks for the code from the app.");
      })
      .catch((err: Error) => setTotpError(plainHubError(err.message)))
      .finally(() => setTotpBusy(false));
  }

  function turnOff() {
    setTotpError(null);
    setTotpOk(null);
    setTotpBusy(true);
    clearTotp()
      .then(() => {
        setSetup(null);
        setCode("");
        setTotp((prev) => (prev ? { ...prev, enrolled: false } : prev));
        setTotpOk("Authenticator is off. Sign-in is the password only.");
      })
      .catch((err: Error) => setTotpError(plainHubError(err.message)))
      .finally(() => setTotpBusy(false));
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
      </aside>
      <main className="terms-main password-main">
        <div className="login-card password-card">
          <h1 className="password-title">Set password</h1>
          <form onSubmit={submit} className="password-form">
            <p className="login-muted">
              Leave both fields blank to keep the current password.
            </p>
            <label className="login-label">
              New password
              <input
                className="login-input"
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                disabled={busy}
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
          {totp?.eligible ? (
            <section className="totp-block">
              <h2 className="password-title">Authenticator</h2>
              {!totp.column_ready ? (
                <p className="login-muted">
                  The authenticator column is not on this login yet. Run hub/sql/totp.sql in SSMS,
                  then open this page again.
                </p>
              ) : setup ? (
                <form onSubmit={confirmSetup} className="password-form">
                  <p className="login-muted">
                    Scan this with an authenticator app, then enter the 6-digit code and press
                    Confirm. That is what stores the secret. A password is not required.
                  </p>
                  <img className="totp-qr" src={setup.qr} alt="Authenticator QR code" />
                  <p className="login-muted">If the camera cannot scan, type this secret into the app.</p>
                  <p className="totp-secret">{setup.secret_groups}</p>
                  <label className="login-label">
                    Code from the app
                    <input
                      className="login-input"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      value={code}
                      onChange={(e) => setCode(e.target.value)}
                      disabled={totpBusy}
                      required
                    />
                  </label>
                  <div className="password-actions">
                    <button
                      className="password-knob password-knob-cancel"
                      type="button"
                      disabled={totpBusy}
                      onClick={() => {
                        setSetup(null);
                        setCode("");
                        setTotpError(null);
                      }}
                    >
                      Cancel
                    </button>
                    <button className="password-knob password-knob-save" type="submit" disabled={totpBusy}>
                      {totpBusy ? "Checking…" : "Confirm"}
                    </button>
                  </div>
                </form>
              ) : totp.enrolled ? (
                <>
                  <p className="login-muted">
                    Authenticator is on. The next sign-in asks for the code from the app.
                  </p>
                  <button
                    className="password-knob password-knob-cancel"
                    type="button"
                    disabled={totpBusy}
                    onClick={turnOff}
                  >
                    {totpBusy ? "Saving…" : "Turn off authenticator"}
                  </button>
                </>
              ) : (
                <>
                  <p className="login-muted">
                    An authenticator app can be the second step for this login. Until you confirm a
                    code, sign-in stays on the password.
                  </p>
                  <button
                    className="password-knob password-knob-save"
                    type="button"
                    disabled={totpBusy}
                    onClick={beginSetup}
                  >
                    {totpBusy ? "Preparing…" : "Set up authenticator"}
                  </button>
                </>
              )}
            </section>
          ) : null}
          {totpError ? <p className="login-error">{totpError}</p> : null}
          {totpOk ? <p className="ok">{totpOk}</p> : null}
        </div>
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

function formatEuro2Display(n: number): string {
  const rounded = Math.round((n + Number.EPSILON) * 100) / 100;
  const sign = rounded < 0 ? "-" : "";
  const [intPart, frac = "00"] = Math.abs(rounded).toFixed(2).split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${sign}${grouped},${frac}`;
}

function formatResultaatPreviewCell(cell: string | number | undefined): string {
  if (cell === "" || cell === undefined) return "";
  return formatDisplayNumber(cell);
}

function formatResultaatEuro2Cell(cell: string | number | undefined): string {
  if (cell === "" || cell === undefined) return "";
  if (typeof cell === "number") {
    return Number.isFinite(cell) ? formatEuro2Display(cell) : "";
  }
  const text = String(cell).trim();
  if (!text) return "";
  const n = Number(text.replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(n) ? formatEuro2Display(n) : text;
}

function ResultaatPreviewTable({
  year,
  dataRev,
  account,
}: {
  year: string;
  dataRev: number;
  account?: string;
}) {
  const [data, setData] = useState<ExportResultaatData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getExportResultaat(year, account)
      .then((payload) => {
        if (cancelled) return;
        setData(payload);
        setError(null);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setData(null);
        setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [year, dataRev, account]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return null;
  const sections = resultaatSections(data);
  if (sections.length === 0) return null;
  const strongLabels = new Set(["Totaal", "Saldo", "Resultaat", "Banksaldo einde maand"]);
  return (
    <div className="resultaat-preview">
      {sections.map((section) => {
        const colCount = section.header.length;
        const hasCumul = section.header[colCount - 1] === "Cumulatief";
        const monthCols = Math.max(0, colCount - 2 - (hasCumul ? 1 : 0));
        return (
          <table
            key={section.title}
            className="totals-table resultaat-preview-table"
            style={{ ["--resultaat-num-cols" as string]: String(Math.max(0, colCount - 2)) }}
          >
            <colgroup>
              <col className="col-code" />
              <col className="col-post" />
              {Array.from({ length: monthCols }, (_, i) => (
                <col key={i} className="col-month" />
              ))}
              {hasCumul ? <col className="col-cumul" /> : null}
            </colgroup>
            <thead>
              <tr>
                <th colSpan={colCount}>{section.title}</th>
              </tr>
              <tr>
                {section.header.map((cell, i) => (
                  <th key={i} className={i >= 2 ? "num" : i === 0 ? "code" : "cat"}>
                    {String(cell)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {section.body.map((row, ri) => {
                if (row.length === 0) {
                  return (
                    <tr key={ri} className="resultaat-spacer-row">
                      <td colSpan={colCount}>&nbsp;</td>
                    </tr>
                  );
                }
                const label = String(row[1] ?? "");
                const twoDecimals = label === "Voedselkosten per tafelgenoot";
                return (
                  <tr key={ri} className={strongLabels.has(label) ? "banksaldo-row" : ""}>
                    {Array.from({ length: colCount }, (_, i) => {
                      const cell = row[i];
                      const isNum = i >= 2;
                      const isCumul = hasCumul && i === colCount - 1;
                      const off =
                        isNum && !isCumul && section.mismatch?.[i - 2] === true;
                      return (
                        <td
                          key={i}
                          className={
                            isNum
                              ? off
                                ? "num resultaat-mismatch"
                                : "num"
                              : i === 0
                                ? "code"
                                : "cat"
                          }
                        >
                          {isNum
                            ? twoDecimals
                              ? formatResultaatEuro2Cell(cell)
                              : formatResultaatPreviewCell(cell)
                            : String(cell ?? "")}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        );
      })}
    </div>
  );
}

function MonthlyDrilldownApp({
  brandName,
  year,
  bankView,
  dataRev,
  bankOptions,
  menuTerms,
}: {
  brandName: string;
  year: string;
  bankView: string;
  dataRev: number;
  bankOptions: BankAccount[];
  menuTerms: Record<string, string>;
}) {
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

  const sidebarTitle = accountSidebarTitle(brandName, bankView, bankOptions, menuTerms);

  return (
    <div className="app">
      <aside className="sidebar">
        {sidebarTitle ? <FitSidebarTitle text={sidebarTitle} /> : null}
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
      </aside>
      <main className="content">
        <ResultaatPreviewTable year={year} dataRev={dataRev} account={bankView} />
      </main>
    </div>
  );
}

function MatrixTable({
  matrix,
  selection,
  omitEmpty = false,
  columnLabel,
  onPick,
}: {
  matrix: MatrixResponse;
  selection: CellSelection | null;
  omitEmpty?: boolean;
  columnLabel?: (person_name: string) => string;
  onPick: (person_name: string, category: string) => void;
}) {
  const { people, cells } = matrix;
  const categories = matrixRowsToShow(
    matrix,
    people.length === 1 ? people[0].person_name : undefined,
    omitEmpty
  );
  const terms = matrix.table_header_terms;
  return (
    <table className="totals-table matrix-table">
      <thead>
        <tr>
          <th className="cat">{tableHeaderTerm(terms, "Category")}</th>
          {people.map((p) => (
            <th key={p.person_name} className="num">
              {columnLabel ? columnLabel(p.person_name) : p.person_name}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {categories.map((cat) => (
          <tr
            key={cat}
            className={`${selection?.category === cat ? "active" : ""}${isMatrixFooter(matrix, cat) ? " banksaldo-row" : ""}${categoryRowGreyed(matrix, cat, people.length === 1 ? people[0].person_name : undefined) ? " empty-category-row" : ""}`}
          >
            <td className="cat">{displayCategoryName(cat)}</td>
            {people.map((p) => {
              const amount = cells[cat]?.[p.person_name] ?? "";
              const isActive =
                selection?.person_name === p.person_name && selection?.category === cat;
              const clickable =
                !isMatrixFooter(matrix, cat) && personHasTransactions(matrix, cat, p.person_name);
              return (
                <td
                  key={p.person_name}
                  className={`num${clickable ? " clickable" : " empty-cell"}${isActive ? " active-cell" : ""}`}
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
  omitEmpty = false,
  columnLabel,
  onPick,
  onPersonChange,
}: {
  matrix: MatrixResponse;
  person_name: string;
  selectedCategory: string | null;
  omitEmpty?: boolean;
  columnLabel?: (person_name: string) => string;
  onPick: (category: string) => void;
  onPersonChange?: (person_name: string) => void;
}) {
  const { people, cells } = matrix;
  const categories = matrixRowsToShow(matrix, person_name, omitEmpty);
  const terms = matrix.table_header_terms;
  const scopedPeople = people.some((p) => p.person_name === person_name)
    ? people
    : [{ person_name }, ...people];
  const showPersonMenu = scopedPeople.length > 1 && Boolean(onPersonChange);
  return (
    <table className="totals-table">
      <thead>
        <tr>
          <th className="cat">{tableHeaderTerm(terms, "Category")}</th>
          <th className="num person-column-head">
            {showPersonMenu ? (
              <select
                className="person-column-select"
                value={person_name}
                aria-label={tableHeaderTerm(terms, "Person")}
                onChange={(e) => {
                  const next = e.target.value;
                  if (next !== person_name) onPersonChange?.(next);
                }}
              >
                {scopedPeople.map((p) => (
                  <option key={p.person_name} value={p.person_name}>
                    {columnLabel ? columnLabel(p.person_name) : p.person_name}
                  </option>
                ))}
              </select>
            ) : (
              columnLabel ? columnLabel(person_name) : person_name
            )}
          </th>
        </tr>
      </thead>
      <tbody>
        {categories.map((cat) => (
          <tr
            key={cat}
            className={`${cat === selectedCategory ? "active" : ""}${isMatrixFooter(matrix, cat) ? " banksaldo-row" : ""}${categoryRowGreyed(matrix, cat, person_name) ? " empty-category-row" : ""}`}
          >
            <td className="cat">{displayCategoryName(cat)}</td>
            {(() => {
              const amount = cells[cat]?.[person_name] ?? "";
              const clickable =
                !isMatrixFooter(matrix, cat) && personHasTransactions(matrix, cat, person_name);
              return (
                <td
                  className={`num${clickable ? " clickable" : " empty-cell"}`}
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

function transactionCents(value: unknown): number {
  if (typeof value === "number") return Number.isFinite(value) ? Math.round(value * 100) : 0;
  const text = String(value ?? "").trim();
  if (!text) return 0;
  const n = Number(text.replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
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

function categoryPickerItems(
  names: string[],
  codes: number[]
): { code: number; label: string; name: string }[] {
  const byCode = new Map<number, { label: string; name: string }>();
  for (const name of names) {
    const match = String(name).match(/^(\d{2,4})(?:\s+(.*))?$/);
    if (!match) continue;
    const code = parseInt(match[1], 10);
    if (!Number.isFinite(code)) continue;
    byCode.set(code, { label: (match[2] ?? "").trim(), name });
  }
  for (const code of codes) {
    if (!Number.isFinite(code)) continue;
    if (!byCode.has(code)) byCode.set(code, { label: "", name: "" });
  }
  return [...byCode.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([code, item]) => ({ code, label: item.label, name: item.name }));
}

function CategoryPickerPopup({
  currentCode,
  extraCodes,
  onPick,
  onClose,
}: {
  currentCode: number | null;
  extraCodes: number[];
  onPick: (code: number) => void;
  onClose: () => void;
}) {
  const [items, setItems] = useState<{ code: number; label: string; name: string }[] | null>(null);
  const extraKey = extraCodes.join(",");

  useEffect(() => {
    let cancelled = false;
    const codes = extraKey
      ? extraKey.split(",").map((part) => Number(part))
      : [];
    getSettings()
      .then((loaded) => {
        if (cancelled) return;
        setItems(
          categoryPickerItems(loaded.categories, [
            ...(loaded.valid_category_codes ?? []),
            ...codes,
          ])
        );
      })
      .catch(() => {
        if (!cancelled) setItems(categoryPickerItems([], codes));
      });
    return () => {
      cancelled = true;
    };
  }, [currentCode, extraKey]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="category-picker-backdrop" onClick={onClose}>
      <div
        className="category-picker"
        role="dialog"
        aria-label="Categorie"
        onClick={(e) => e.stopPropagation()}
      >
        {items == null ? (
          <p className="category-picker-loading">Loading…</p>
        ) : (
          <table className="category-picker-table">
            <thead>
              <tr>
                <th className="code">Code</th>
                <th>Post</th>
              </tr>
            </thead>
            <tbody>
              <tr className="category-picker-row category-picker-cancel" onClick={onClose}>
                <td colSpan={2}>cancel</td>
              </tr>
              {items.map((item) => (
                <tr
                  key={item.code}
                  className={`category-picker-row${item.code === currentCode ? " selected" : ""}`}
                  onClick={() => onPick(item.code)}
                >
                  <td className="code">
                    {String(item.code).padStart(item.code < 100 ? 2 : 4, "0")}
                  </td>
                  <td>{item.label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function SearchStatementsApp({ terms }: { terms: Record<string, string> }) {
  const [options, setOptions] = useState<BookingSearchOptions | null>(null);
  const [result, setResult] = useState<BookingSearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [description, setDescription] = useState("");
  const [name, setName] = useState("");
  const [amountFrom, setAmountFrom] = useState("");
  const [amountTo, setAmountTo] = useState("");
  const [bankType, setBankType] = useState("");
  const [accountIban, setAccountIban] = useState("");
  const [counterpartyIban, setCounterpartyIban] = useState("");
  const [localCode, setLocalCode] = useState("");

  const labels = options?.table_header_terms ?? terms;

  useEffect(() => {
    let cancelled = false;
    getBookingSearchOptions()
      .then((payload) => {
        if (!cancelled) setOptions(payload);
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

  function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    searchBookings({
      date_from: dateFrom,
      date_to: dateTo,
      description,
      name,
      amount_from: amountFrom,
      amount_to: amountTo,
      bank_type: bankType,
      account_iban: accountIban,
      counterparty_iban: counterpartyIban,
      local_code: localCode,
    })
      .then((payload) => setResult(payload))
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  }

  const transactions = result?.transactions ?? [];
  const headerTerms = result?.table_header_terms ?? labels;
  const abbreviations = result?.abbreviations ?? options?.abbreviations ?? {};
  const columns = categoryBeforeDescription(
    stripHiddenColumns(
      result?.columns?.length ? result.columns : ptableColumns(transactions)
    )
  );

  return (
    <div className="app search-app">
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
        <form className="search-criteria" onSubmit={submit}>
          <label className="login-label">
            {tableHeaderTerm(labels, "Date from")}
            <input
              className="login-input"
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
            />
          </label>
          <label className="login-label">
            {tableHeaderTerm(labels, "Date to")}
            <input
              className="login-input"
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
            />
          </label>
          <label className="login-label">
            {tableHeaderTerm(labels, "Text in description")}
            <input
              className="login-input"
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          <label className="login-label">
            {tableHeaderTerm(labels, "Text in name")}
            <input
              className="login-input"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="login-label">
            {tableHeaderTerm(labels, "Amount from")}
            <input
              className="login-input"
              type="text"
              inputMode="decimal"
              value={amountFrom}
              onChange={(e) => setAmountFrom(e.target.value)}
            />
          </label>
          <label className="login-label">
            {tableHeaderTerm(labels, "Amount to")}
            <input
              className="login-input"
              type="text"
              inputMode="decimal"
              value={amountTo}
              onChange={(e) => setAmountTo(e.target.value)}
            />
          </label>
          <label className="login-label">
            {tableHeaderTerm(labels, "Type")}
            <input
              className="login-input"
              type="text"
              value={bankType}
              onChange={(e) => setBankType(e.target.value)}
            />
          </label>
          <label className="login-label">
            {tableHeaderTerm(labels, "Account holder IBAN")}
            <select
              className="login-input"
              value={accountIban}
              onChange={(e) => setAccountIban(e.target.value)}
            >
              <option value="" />
              {(options?.ibans ?? []).map((iban) => (
                <option key={iban} value={iban}>
                  {iban}
                </option>
              ))}
            </select>
          </label>
          <label className="login-label">
            {tableHeaderTerm(labels, "Counterparty IBAN")}
            <select
              className="login-input"
              value={counterpartyIban}
              onChange={(e) => setCounterpartyIban(e.target.value)}
            >
              <option value="" />
              {(options?.ibans ?? []).map((iban) => (
                <option key={`cp-${iban}`} value={iban}>
                  {iban}
                </option>
              ))}
            </select>
          </label>
          <label className="login-label">
            {tableHeaderTerm(labels, "Category")}
            <select
              className="login-input"
              value={localCode}
              onChange={(e) => setLocalCode(e.target.value)}
            >
              <option value="" />
              {(options?.categories ?? []).map((cat) => (
                <option key={cat.local_code} value={String(cat.local_code)}>
                  {cat.local_code} {cat.label}
                </option>
              ))}
            </select>
          </label>
          {error ? <p className="login-error">{error}</p> : null}
          <button className="sidebar-knob" type="submit" disabled={busy}>
            {busy ? "…" : tableHeaderTerm(labels, "Search")}
          </button>
        </form>
      </aside>
      <main className="content">
        {result ? (
          transactions.length === 0 ? (
            <p>{tableHeaderTerm(labels, "No bookings")}</p>
          ) : (
            <div className="p-panel">
              {result.limited ? (
                <p>{tableHeaderTerm(labels, "Showing the first 500 bookings")}</p>
              ) : null}
              <div className="p-details-row">
                <div className="p-account-iban">
                  <strong>Rekeninghouder</strong>
                  <table className="p-table">
                    <thead>
                      <tr>
                        <th>IBAN</th>
                      </tr>
                    </thead>
                    <tbody>
                      {transactions.map((t) => (
                        <tr key={String(t.id)}>
                          <td>{formatCell(t.account_iban)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="p-details">
                  <strong>Details</strong>
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
                            {c === "iban"
                              ? "IBAN tegenpartij"
                              : <RichLabel text={columnHeaderLabel(c, headerTerms)} />}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {transactions.map((t) => (
                        <tr key={String(t.id)}>
                          {columns.map((c) => {
                            if (c === "amount") {
                              const negative =
                                String(t.amount ?? "").trim().startsWith("-") ||
                                Number(t.amount) < 0;
                              return (
                                <td
                                  key={c}
                                  className={negative ? "amount num neg" : "amount num"}
                                >
                                  {formatDisplayNumber(t.amount)}
                                </td>
                              );
                            }
                            if (c === "type") {
                              return <td key={c}>{abbreviate(abbreviations, t.type)}</td>;
                            }
                            return <td key={c}>{formatCell(t[c])}</td>;
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )
        ) : null}
      </main>
    </div>
  );
}

function PTable({
  categoryName,
  detail,
  year,
  bank,
  languageLong,
  onModify,
  onCategoryError,
  onTermContextMenu,
}: {
  categoryName: string;
  detail: TransactionsResponse;
  year?: string;
  bank?: string;
  languageLong?: Record<string, string>;
  onModify: (transaction: Transaction) => void;
  onCategoryError?: (message: string | null) => void;
  onTermContextMenu?: (e: MouseEvent, cellText: string, transactionId: string) => void;
}) {
  const [picker, setPicker] = useState<Transaction | null>(null);
  const [signOpen, setSignOpen] = useState(false);
  const transactions = Array.isArray(detail.transactions) ? detail.transactions : [];
  const keywords = Array.isArray(detail.keywords) ? detail.keywords : [];
  const validCategoryCodes = new Set(detail.valid_category_codes ?? []);
  const columns = categoryBeforeDescription(
    stripHiddenColumns(
      Array.isArray(detail.columns) && detail.columns.length > 0
        ? detail.columns
        : ptableColumns(transactions)
    )
  );

  const consolidated = useMemo(() => {
    const totals = new Map<string, number>();
    for (const t of transactions) {
      const name = formatCell(t.name).trim();
      if (!name) continue;
      totals.set(name, (totals.get(name) ?? 0) + transactionCents(t.amount));
    }
    return [...totals.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([name, cents]) => ({ name, cents }));
  }, [transactions]);

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
      const flag = Number(t.modification);
      const descModified = flag === 3 || flag === 4;
      return (
        <td
          key={column}
          className={`desc term-source${descModified ? " description-modified" : ""}`}
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
      const flag = Number(t.modification);
      const catModified = flag === 2 || flag === 4;
      return (
        <td
          key={column}
          className={`num category-pick${catModified ? " category-modified" : ""}`}
          onClick={() => setPicker(t)}
        >
          <span className="editable">{formatCell(t.category)}</span>
        </td>
      );
    }
    return <td key={column}>{formatCell(t[column])}</td>;
  }

  const signLabel = tableHeaderTerm(detail.table_header_terms, "Sign convention transactions");
  return (
    <div className="p-panel">
      <button type="button" className="sidebar-knob info-knob" onClick={() => setSignOpen(true)}>
        <RichLabel text={signLabel} />
      </button>
      {signOpen ? (
        <PriorityRulesDialog
          title={signLabel}
          body={
            languageLong?.["sign convention transactions"] ??
            languageLong?.["sign convention"] ??
            ""
          }
          closeLabel={tableHeaderTerm(detail.table_header_terms, "Close")}
          onClose={() => setSignOpen(false)}
        />
      ) : null}
      <div className="p-heading">
        <strong>
          {detail.person} / {displayCategoryName(categoryName)}
        </strong>
      </div>
      {transactions.length === 0 ? (
        <p>Geen transacties in deze categorie.</p>
      ) : (
        <>
          {consolidated.length > 0 && (
            <div className="p-consolidated">
              <strong>Totale bijdrage per tegenpartij</strong>
              <table className="p-table">
                <thead>
                  <tr>
                    <th className="num">
                      <RichLabel text={columnHeaderLabel("amount", detail.table_header_terms)} />
                    </th>
                    <th><RichLabel text={columnHeaderLabel("name", detail.table_header_terms)} /></th>
                  </tr>
                </thead>
                <tbody>
                  {consolidated.map(({ name, cents }) => (
                    <tr key={name}>
                      <td className={cents < 0 ? "amount num neg" : "amount num"}>
                        {formatUnity(cents / 100)}
                      </td>
                      <td>{name}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="p-details-row">
            <div className="p-account-iban">
              <strong>Rekeninghouder</strong>
              <table className="p-table">
                <thead>
                  <tr>
                    <th>IBAN</th>
                  </tr>
                </thead>
                <tbody>
                  {transactions.map((t) => (
                    <tr key={String(t.id)}>
                      <td>{formatCell(t.account_iban)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="p-details">
              <strong>Details</strong>
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
                        {c === "iban"
                          ? "IBAN tegenpartij"
                          : <RichLabel text={columnHeaderLabel(c, detail.table_header_terms)} />}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {transactions.map((t) => (
                    <tr key={String(t.id)}>
                      {columns.map((c) => renderCell(t, c))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
      {picker ? (
        <CategoryPickerPopup
          currentCode={Number(picker.category)}
          extraCodes={[...validCategoryCodes]}
          onPick={(code) => {
            handsetDebug("categoryPicker.onPick", {
              code,
              id: picker.id,
              name: picker.name,
              modification: 2,
            });
            setPicker(null);
            onCategoryError?.(null);
            onModify({ ...picker, category: code, modification: 2 });
          }}
          onClose={() => setPicker(null)}
        />
      ) : null}
    </div>
  );
}

function TermContextMenu({
  settings,
  initialTerm,
  personScope,
  showCenters,
  bankIban,
  generalEditable = true,
  x,
  y,
  onClose,
  onPickCategory,
}: {
  settings: SettingsResponse;
  initialTerm: string;
  personScope?: string;
  showCenters?: boolean;
  bankIban?: string;
  /** Country login only. Other logins see the G column greyed out. */
  generalEditable?: boolean;
  x: number;
  y: number;
  onClose: () => void;
  onPickCategory: (
    term: string,
    targetCategory: string,
    general: boolean,
    account?: string
  ) => void | Promise<void>;
}) {
  const [term, setTerm] = useState(initialTerm);
  const [saving, setSaving] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState({ left: x, top: y });

  const accountGroups = scopedAccountGroups(settings.account_groups, personScope);
  const accountModality = accountGroups.length > 0;
  const menuBlocks = accountBlocks(accountGroups, "");
  const listCenters = Boolean(showCenters && menuBlocks.some((block) => block.center));
  const [accountKey, setAccountKey] = useState(() => {
    const preset = bankIban
      ? accountGroups.find(
          (g) =>
            String(g.iban ?? "").trim().toUpperCase() ===
            String(bankIban).trim().toUpperCase()
        )
      : undefined;
    return preset?.account_key ?? accountGroups[0]?.account_key ?? "";
  });
  const centerPicked = Boolean(centerNameFromKey(accountKey));

  const categories = settings.categories.filter(
    (name) =>
      name !== settings.remainder_category && isHitCategoryName(name, settings)
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
  }, [x, y, categories.length, initialTerm, accountModality]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function pick(category: string, general: boolean) {
    const cleaned = term.trim();
    handsetDebug("termContext.pick", { category, general, term: cleaned });
    if (!cleaned || saving) return;
    if (general && !generalEditable) return;
    setSaving(true);
    Promise.resolve(
      onPickCategory(
        cleaned,
        category,
        general,
        general ? undefined : accountKey || undefined
      )
    ).finally(() => setSaving(false));
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
                  {accountModality ? (
                    <select
                      className={
                        centerPicked
                          ? "term-context-account-select center-picked"
                          : "term-context-account-select"
                      }
                      value={accountKey}
                      title={tableHeaderTerm(settings.table_header_terms, "Personal")}
                      disabled={saving}
                      onChange={(e) => setAccountKey(e.target.value)}
                      onClick={(e) => e.stopPropagation()}
                    >
                      {(listCenters ? menuBlocks : [{ center: "", key: "", accounts: accountGroups }]).flatMap(
                        (block) => [
                          listCenters && block.center ? (
                            <option
                              key={block.key}
                              value={block.key}
                              style={{ color: "#b91c1c", fontWeight: 600 }}
                            >
                              {block.center}
                            </option>
                          ) : null,
                          ...block.accounts.map((group) => (
                            <option key={group.account_key} value={group.account_key}>
                              {listCenters
                                ? `\u00a0\u00a0${group.account_name || group.account_key}`
                                : group.account_name || group.account_key}
                            </option>
                          )),
                        ]
                      )}
                    </select>
                  ) : (
                    tableHeaderTerm(settings.table_header_terms, "P")
                  )}
                </th>
              </tr>
            </thead>
            <tbody>
              {categories.map((name) => (
                <tr key={name}>
                  <td className="term-context-cat">{displayCategoryName(name)}</td>
                  <td className={generalEditable ? "term-context-gp" : "term-context-gp locked"}>
                    <input
                      type="checkbox"
                      aria-label={`${name} general`}
                      disabled={saving || !term.trim() || !generalEditable}
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
    (name) =>
      name !== settings.remainder_category && isHitCategoryName(name, settings)
  );
}

function patchCategories(
  categories: Record<string, string[]> | undefined,
  category: string,
  terms: string[]
): Record<string, string[]> {
  const next = { ...(categories ?? {}) };
  if (terms.length) next[category] = terms;
  else delete next[category];
  return next;
}

/** Stable empty list so `?? EMPTY_TERMS` does not allocate a new [] every render. */
const EMPTY_TERMS: string[] = [];

const CENTER_ACCOUNT_PREFIX = "__center__:";

function centerAccountKey(centerName: string): string {
  return `${CENTER_ACCOUNT_PREFIX}${centerName}`;
}

function centerNameFromKey(key: string): string {
  return key.startsWith(CENTER_ACCOUNT_PREFIX)
    ? key.slice(CENTER_ACCOUNT_PREFIX.length)
    : "";
}

type AccountBlock = {
  center: string;
  key: string;
  accounts: AccountGroup[];
};

function accountBlocks(groups: AccountGroup[], fallbackCenter: string): AccountBlock[] {
  const buckets = new Map<string, AccountGroup[]>();
  for (const group of groups) {
    const center = (group.center || fallbackCenter || "").trim();
    const list = buckets.get(center) ?? [];
    list.push(group);
    buckets.set(center, list);
  }
  return [...buckets.keys()]
    .sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }))
    .map((center) => ({
      center,
      key: center ? centerAccountKey(center) : "",
      accounts: [...(buckets.get(center) ?? [])].sort((a, b) =>
        (a.account_name || a.account_key).localeCompare(
          b.account_name || b.account_key,
          undefined,
          { sensitivity: "base" }
        )
      ),
    }));
}

function unionAccountTerms(
  groups: AccountGroup[],
  category: string
): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const group of groups) {
    for (const term of group.categories[category] ?? []) {
      const text = String(term || "").trim();
      if (!text || seen.has(text)) continue;
      seen.add(text);
      out.push(text);
    }
  }
  return sortTerms(out);
}

function TermsTables({
  settings,
  personScope,
  centerName,
  generalEditable = true,
  onUpdate,
  onUpdateMany,
  onUpdateCenter,
}: {
  settings: SettingsResponse;
  personScope?: string;
  centerName?: string;
  /** Country login only. Other logins see G-terms greyed out. */
  generalEditable?: boolean;
  onUpdate: (group: string, category: string, terms: string[]) => void;
  onUpdateMany?: (
    items: { group: string; category: string; terms: string[] }[]
  ) => void;
  onUpdateCenter?: (
    category: string,
    add: string[],
    remove: string[],
    center?: string
  ) => void;
}) {
  const { people, general, personal } = settings;
  const account_groups = scopedAccountGroups(settings.account_groups, personScope);
  const blocks = accountBlocks(account_groups, personScope ? "" : (centerName || "").trim());
  const [selectedPerson, setSelectedPerson] = useState(people[0]?.person_name ?? "");
  const [selectedAccount, setSelectedAccount] = useState(account_groups[0]?.account_key ?? "");
  const selectedAccountGroup = account_groups.find((g) => g.account_key === selectedAccount);
  const columns = termsTableCategories(settings);
  const accountModality = Boolean(account_groups && account_groups.length > 0);
  const showCenters = Boolean(!personScope && accountModality && blocks.some((block) => block.center));

  const [selectedCategory, setSelectedCategory] = useState(columns[0] ?? "");

  useEffect(() => {
    if (!columns.includes(selectedCategory)) {
      setSelectedCategory(columns[0] ?? "");
    }
  }, [columns, selectedCategory]);

  useEffect(() => {
    const pickedCenter = centerNameFromKey(selectedAccount);
    if (pickedCenter && blocks.some((block) => block.center === pickedCenter)) return;
    if (
      account_groups.length > 0 &&
      !account_groups.some((group) => group.account_key === selectedAccount)
    ) {
      setSelectedAccount(account_groups[0].account_key);
    }
  }, [account_groups, selectedAccount, blocks]);

  const selectedGroupKey = accountModality ? selectedAccount : selectedPerson;
  const selectedCenter = showCenters ? centerNameFromKey(selectedAccount) : "";
  const centerSelected = Boolean(selectedCenter);
  const centerGroups = centerSelected
    ? (blocks.find((block) => block.center === selectedCenter)?.accounts ?? [])
    : [];

  const gTerms = selectedCategory ? (general[selectedCategory] ?? EMPTY_TERMS) : EMPTY_TERMS;
  const pTerms = selectedCategory
    ? accountModality
      ? centerSelected
        ? unionAccountTerms(centerGroups, selectedCategory)
        : (selectedAccountGroup?.categories[selectedCategory] ?? EMPTY_TERMS)
      : (personal[selectedPerson]?.[selectedCategory] ?? EMPTY_TERMS)
    : EMPTY_TERMS;
  const personalEditable = Boolean(
    selectedCategory &&
      (accountModality
        ? centerSelected
          ? centerGroups.length > 0
          : selectedAccount
        : selectedPerson)
  );

  function commitPersonal(next: string[]) {
    if (!selectedCategory) return;
    if (centerSelected) {
      const previous = new Set(pTerms);
      const incoming = new Set(next);
      const added = next.filter((term) => !previous.has(term));
      const removed = pTerms.filter((term) => !incoming.has(term));
      if (onUpdateCenter) {
        onUpdateCenter(selectedCategory, added, removed, selectedCenter);
        return;
      }
      const items = centerGroups.map((group) => {
        const current = group.categories[selectedCategory] ?? [];
        const merged = [
          ...current.filter((term) => !removed.includes(term)),
          ...added.filter((term) => !current.includes(term)),
        ];
        return {
          group: group.account_key,
          category: selectedCategory,
          terms: sortTerms(merged),
        };
      });
      (onUpdateMany ?? ((rows) => rows.forEach((row) => onUpdate(row.group, row.category, row.terms))))(
        items
      );
      return;
    }
    onUpdate(selectedGroupKey, selectedCategory, next);
  }

  return (
    <div className="terms-scroll">
      <div className="terms-four">
        <section className="terms-col" aria-label="Categories">
          <h2 className="terms-panel-label">
            {tableHeaderTerm(settings.table_header_terms, "Category")}
          </h2>
          <div className="terms-list">
            {columns.map((name) => (
              <button
                key={name}
                type="button"
                className={
                  name === selectedCategory ? "terms-list-item selected" : "terms-list-item"
                }
                onClick={() => setSelectedCategory(name)}
              >
                {displayCategoryName(name)}
              </button>
            ))}
          </div>
        </section>

        <section className="terms-col" aria-label="General terms">
          <h2 className="terms-panel-label">
            {tableHeaderTerm(settings.table_header_terms, "General")}
          </h2>
          <div className={generalEditable ? "terms-cell" : "terms-cell terms-cell-locked"}>
            {selectedCategory ? (
              <EditableCell
                terms={gTerms}
                readOnly={!generalEditable}
                onCommit={(t) => onUpdate("general", selectedCategory, t)}
              />
            ) : (
              <p className="terms-empty">No category selected</p>
            )}
          </div>
        </section>

        <section className="terms-col" aria-label="People">
          <h2 className="terms-panel-label">
            {accountModality
              ? tableHeaderTerm(settings.table_header_terms, "Account")
              : tableHeaderTerm(settings.table_header_terms, "Person")}
          </h2>
          <div className="terms-list">
            {accountModality ? (
              showCenters ? (
                blocks.map((block) => (
                  <Fragment key={block.key || block.center}>
                    {block.center ? (
                      <button
                        type="button"
                        className={
                          selectedAccount === block.key
                            ? "terms-list-item term-center selected"
                            : "terms-list-item term-center"
                        }
                        onClick={() => setSelectedAccount(block.key)}
                      >
                        {block.center}
                        <span className="terms-list-sub">center</span>
                      </button>
                    ) : null}
                    {block.accounts.map((g) => (
                      <button
                        key={g.account_key}
                        type="button"
                        className={
                          g.account_key === selectedAccount
                            ? "terms-list-item selected"
                            : "terms-list-item"
                        }
                        onClick={() => setSelectedAccount(g.account_key)}
                      >
                        {g.account_name || g.account_key}
                        {g.person ? <span className="terms-list-sub">{g.person}</span> : null}
                      </button>
                    ))}
                  </Fragment>
                ))
              ) : (
                (account_groups ?? []).map((g) => (
                  <button
                    key={g.account_key}
                    type="button"
                    className={
                      g.account_key === selectedAccount
                        ? "terms-list-item selected"
                        : "terms-list-item"
                    }
                    onClick={() => setSelectedAccount(g.account_key)}
                  >
                    {g.account_name || g.account_key}
                    {g.person ? <span className="terms-list-sub">{g.person}</span> : null}
                  </button>
                ))
              )
            ) : (
              people.map((p) => (
                <button
                  key={p.person_name}
                  type="button"
                  className={
                    p.person_name === selectedPerson
                      ? "terms-list-item selected"
                      : "terms-list-item"
                  }
                  onClick={() => setSelectedPerson(p.person_name)}
                >
                  {p.person_name}
                </button>
              ))
            )}
          </div>
        </section>

        <section className="terms-col" aria-label="Personal terms">
          <h2 className="terms-panel-label">
            {tableHeaderTerm(settings.table_header_terms, "Personal")}
          </h2>
          <div className="terms-cell">
            {personalEditable ? (
              <EditableCell
                terms={pTerms}
                onCommit={commitPersonal}
              />
            ) : (
              <p className="terms-empty">
                {selectedCategory ? "No person or account selected" : "No category selected"}
              </p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function sortTerms(values: string[]): string[] {
  return [...values].sort((a, b) => a.localeCompare(b));
}

function EditableCell({
  terms,
  readOnly = false,
  onCommit,
}: {
  terms: string[];
  readOnly?: boolean;
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
    <div className={readOnly ? "terms terms-readonly" : "terms"}>
      {draft.map((term, i) => (
        <div key={i} className="term-row">
          <input
            className="term-input"
            value={term}
            readOnly={readOnly}
            disabled={readOnly}
            onChange={(e) => {
              if (readOnly) return;
              const value = e.target.value;
              setDraft((d) => {
                const next = d.map((t, idx) => (idx === i ? value : t));
                draftRef.current = next;
                return next;
              });
            }}
            onBlur={() => {
              if (!readOnly) commit(draftRef.current);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
            }}
          />
          {readOnly ? null : (
            <button
              type="button"
              className="term-delete"
              title="Delete term"
              onClick={() => removeAt(i)}
            >
              ×
            </button>
          )}
        </div>
      ))}
      {readOnly ? null : (
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
      )}
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

const HIDDEN_TRANSACTION_COLUMNS = new Set([
  "id",
  "currency",
  "modification",
  "hit",
  "account_uid",
  "account_iban",
  "journal_src",
]);

function stripHiddenColumns(columns: string[]): string[] {
  return columns.filter((c) => !HIDDEN_TRANSACTION_COLUMNS.has(c));
}

function ptableColumns(transactions: Transaction[]): string[] {
  const columns: string[] = [];
  for (const t of transactions) {
    for (const key of Object.keys(t)) {
      if (!HIDDEN_TRANSACTION_COLUMNS.has(key) && !columns.includes(key)) {
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

function findLiteralRanges(term: string, candidate: string): Array<[number, number]> | null {
  const parts = term.toLowerCase().split("#");
  let pos = 0;
  const ranges: Array<[number, number]> = [];
  for (const part of parts) {
    if (!part) continue;
    const at = candidate.indexOf(part, pos);
    if (at < 0) return null;
    ranges.push([at, at + part.length]);
    pos = at + part.length;
  }
  return ranges;
}

function strippedIndexMap(word: string): number[] {
  const map: number[] = [];
  for (let i = 0; i < word.length; i++) {
    if (/[a-z.]/i.test(word[i])) map.push(i);
  }
  return map;
}

function hashLiteralRanges(term: string, word: string): Array<[number, number]> {
  if (new RegExp(`^${termToPattern(term)}$`, "i").test(word)) {
    return findLiteralRanges(term, word.toLowerCase()) ?? [];
  }
  const stripped = lettersOnly(word);
  const inner = stripped ? findLiteralRanges(term, stripped) : null;
  if (!inner) return [];
  const map = strippedIndexMap(word);
  return inner.map(([start, end]) => [map[start], map[end - 1] + 1]);
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
  const hashPhraseTerms = terms.filter((t) => t.includes("#") && t.includes(" "));
  const plainTerms = terms.filter((t) => !t.includes("#"));

  if (hashWordTerms.length === 0 && hashPhraseTerms.length === 0) {
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
        for (const term of hashWordTerms) {
          if (!matchesHashWord(term, word)) continue;
          for (const [from, to] of hashLiteralRanges(term, word)) {
            ranges.push([start + from, start + to]);
          }
        }
      }
    }
  }

  for (const term of hashPhraseTerms) {
    const re = new RegExp(`\\b${termToPattern(term)}\\b`, "gi");
    for (const match of text.matchAll(re)) {
      const start = match.index ?? 0;
      const inner = findLiteralRanges(term, match[0].toLowerCase());
      if (!inner) continue;
      for (const [from, to] of inner) ranges.push([start + from, start + to]);
    }
  }

  if (ranges.length === 0) return text;
  return highlightRanges(text, ranges);
}
