export type XlsxCellValue = string | number;

export interface XlsxStyle {
  bold?: boolean;
  fontSize?: number;
  /** Hex color without leading "#", e.g. "FF0000". */
  fontColor?: string;
  /** Hex color without leading "#", e.g. "FFFF00". */
  background?: string;
  borderBottom?: boolean;
  /** OOXML number-format code for number cells; default "#,##0.00". */
  format?: string;
}

export type XlsxCell =
  | XlsxCellValue
  | { value: XlsxCellValue; style?: XlsxStyle };

export interface XlsxSheet {
  name: string;
  rows: XlsxCell[][];
  widths?: number[];
}

const XML_ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&apos;",
};

function escXml(text: string): string {
  return text.replace(/[&<>"']/g, (ch) => XML_ESCAPES[ch] ?? ch);
}

function colLetter(idx: number): string {
  let result = "";
  let n = idx + 1;
  while (n > 0) {
    const rem = (n - 1) % 26;
    result = String.fromCharCode(65 + rem) + result;
    n = Math.floor((n - 1) / 26);
  }
  return result;
}

const DEFAULT_FONT_SIZE = 11;
const DEFAULT_FONT_COLOR = "FF1A1A1A";
const CURRENCY_FORMAT = "#,##0.00";

interface ResolvedStyle {
  bold: boolean;
  fontSize: number;
  fontColor: string;
  background: string;
  borderBottom: boolean;
  isNumber: boolean;
  formatCode: string;
}

function hexColor(value: string | undefined, fallback: string): string {
  if (!value) return fallback;
  const hex = value.replace(/^#/, "").toUpperCase();
  if (/^[0-9A-F]{8}$/.test(hex)) return hex;
  if (/^[0-9A-F]{6}$/.test(hex)) return `FF${hex}`;
  return fallback;
}

function resolveStyle(cell: XlsxCell): ResolvedStyle {
  const style =
    typeof cell === "object" && cell !== null ? cell.style ?? {} : {};
  const value =
    typeof cell === "object" && cell !== null ? cell.value : cell;
  return {
    bold: style.bold === true,
    fontSize: style.fontSize ?? DEFAULT_FONT_SIZE,
    fontColor: hexColor(style.fontColor, DEFAULT_FONT_COLOR),
    background: hexColor(style.background, ""),
    borderBottom: style.borderBottom === true,
    isNumber: typeof value === "number",
    formatCode: style.format ?? (typeof value === "number" ? CURRENCY_FORMAT : ""),
  };
}

interface StyleRegistry {
  fonts: ResolvedStyle[];
  fills: string[];
  numFmts: { id: number; code: string }[];
  xfs: { fontId: number; fillId: number; numFmtId: number; borderId: number }[];
  styleIdOf: (cell: XlsxCell) => number;
}

function buildRegistry(sheets: XlsxSheet[]): StyleRegistry {
  const fonts: ResolvedStyle[] = [];
  const fills: string[] = [];
  const numFmts: { id: number; code: string }[] = [];
  const xfs: { fontId: number; fillId: number; numFmtId: number; borderId: number }[] = [];
  const fontIds = new Map<string, number>();
  const fillIds = new Map<string, number>();
  const numFmtIds = new Map<string, number>();
  const xfIds = new Map<string, number>();
  const styleIds = new Map<string, number>();

  function numFmtIdOf(code: string): number {
    if (!code) return 0;
    let id = numFmtIds.get(code);
    if (id === undefined) {
      id = 164 + numFmts.length;
      numFmts.push({ id, code });
      numFmtIds.set(code, id);
    }
    return id;
  }

  numFmtIdOf(CURRENCY_FORMAT); // reserve the default number format at id 164

  function fontIdOf(style: ResolvedStyle): number {
    const key = `b${+style.bold}|s${style.fontSize}|c${style.fontColor}`;
    let id = fontIds.get(key);
    if (id === undefined) {
      id = fonts.length;
      fonts.push(style);
      fontIds.set(key, id);
    }
    return id;
  }

  function fillIdOf(background: string): number {
    if (!background) return 0;
    let idx = fillIds.get(background);
    if (idx === undefined) {
      idx = fills.length;
      fills.push(background);
      fillIds.set(background, idx);
    }
    return idx + 2; // 0 none, 1 gray125
  }

  function xfIdOf(fontId: number, fillId: number, numFmtId: number, borderId: number): number {
    const key = `${fontId}|${fillId}|${numFmtId}|${borderId}`;
    let id = xfIds.get(key);
    if (id === undefined) {
      id = xfs.length;
      xfs.push({ fontId, fillId, numFmtId, borderId });
      xfIds.set(key, id);
    }
    return id;
  }

  function styleIdOf(cell: XlsxCell): number {
    const style = resolveStyle(cell);
    const key =
      `s${style.fontSize}|b${+style.bold}|c${style.fontColor}` +
      `|g${style.background}|n${+style.isNumber}|br${+style.borderBottom}` +
      `|f${style.formatCode}`;
    let id = styleIds.get(key);
    if (id === undefined) {
      const fontId = fontIdOf(style);
      const fillId = fillIdOf(style.background);
      const numFmtId = style.isNumber ? numFmtIdOf(style.formatCode) : 0;
      const borderId = style.borderBottom ? 1 : 0;
      id = xfIdOf(fontId, fillId, numFmtId, borderId);
      styleIds.set(key, id);
    }
    return id;
  }

  styleIdOf(""); // register the plain default style at xf index 0
  for (const sheet of sheets) {
    for (const row of sheet.rows) {
      for (const cell of row) styleIdOf(cell);
    }
  }
  return { fonts, fills, numFmts, xfs, styleIdOf };
}

function fontXml(style: ResolvedStyle): string {
  const bold = style.bold ? "<b/>" : "";
  return (
    `<font>${bold}<sz val="${style.fontSize}"/>` +
    `<color rgb="${style.fontColor}"/><name val="Calibri"/><family val="2"/><scheme val="minor"/></font>`
  );
}

function xfXml(x: { fontId: number; fillId: number; numFmtId: number; borderId: number }): string {
  const applyFont = x.fontId !== 0 ? ' applyFont="1"' : "";
  const applyFill = x.fillId !== 0 ? ' applyFill="1"' : "";
  const applyBorder = x.borderId !== 0 ? ' applyBorder="1"' : "";
  const applyNumberFormat = x.numFmtId !== 0 ? ' applyNumberFormat="1"' : "";
  return (
    `<xf numFmtId="${x.numFmtId}" fontId="${x.fontId}" fillId="${x.fillId}"` +
    ` borderId="${x.borderId}" xfId="0"${applyFont}${applyFill}${applyBorder}${applyNumberFormat}/>`
  );
}

function stylesXml(reg: StyleRegistry): string {
  const numFmts = reg.numFmts.length
    ? `<numFmts count="${reg.numFmts.length}">${reg.numFmts
        .map(
          (nt) =>
            `<numFmt numFmtId="${nt.id}" formatCode="${escXml(nt.code)}"/>`
        )
        .join("")}</numFmts>`
    : "";
  const fonts = `<fonts count="${reg.fonts.length}">${reg.fonts.map(fontXml).join("")}</fonts>`;
  const fills =
    `<fills count="${reg.fills.length + 2}">` +
    `<fill><patternFill patternType="none"/></fill>` +
    `<fill><patternFill patternType="gray125"/></fill>` +
    reg.fills
      .map(
        (color) =>
          `<fill><patternFill patternType="solid"><fgColor rgb="${color}"/><bgColor indexed="64"/></patternFill></fill>`
      )
      .join("") +
    `</fills>`;
  const borders =
    `<borders count="2">` +
    `<border><left/><right/><top/><bottom/><diagonal/></border>` +
    `<border><left/><right/><top/><bottom style="thin"><color rgb="FF000000"/></bottom><diagonal/></border>` +
    `</borders>`;
  const cellStyleXfs = `<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>`;
  const cellXfs = `<cellXfs count="${reg.xfs.length}">${reg.xfs.map(xfXml).join("")}</cellXfs>`;
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">${numFmts}${fonts}${fills}${borders}${cellStyleXfs}${cellXfs}<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`;
}

function sheetXml(sheet: XlsxSheet, styleIdOf: (cell: XlsxCell) => number): string {
  const rowsXml = sheet.rows
    .map((row, ri) => {
      if (row.length === 0) return "";
      const r = ri + 1;
      const cellsXml = row
        .map((cell, ci) => {
          const ref = `${colLetter(ci)}${r}`;
          const styleId = styleIdOf(cell);
          if (typeof cell === "object") {
            if (typeof cell.value === "number") {
              return `<c r="${ref}" s="${styleId}"><v>${cell.value}</v></c>`;
            }
            return `<c r="${ref}" s="${styleId}" t="inlineStr"><is><t>${escXml(String(cell.value))}</t></is></c>`;
          }
          if (typeof cell === "number") {
            return `<c r="${ref}" s="${styleId}"><v>${cell}</v></c>`;
          }
          return `<c r="${ref}" s="${styleId}" t="inlineStr"><is><t>${escXml(cell)}</t></is></c>`;
        })
        .join("");
      return `<row r="${r}">${cellsXml}</row>`;
    })
    .join("");
  const colCount = Math.max(1, ...sheet.rows.map((row) => row.length));
  const lastCol = colLetter(colCount - 1);
  const colsXml =
    sheet.widths && sheet.widths.length > 0
      ? `<cols>${sheet.widths
          .map(
            (w, i) =>
              `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`
          )
          .join("")}</cols>`
      : "";
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:${lastCol}${sheet.rows.length}"/>${colsXml}<sheetData>${rowsXml}</sheetData></worksheet>`;
}

function workbookXml(sheets: XlsxSheet[]): string {
  const sheetsXml = sheets
    .map(
      (sheet, i) =>
        `<sheet name="${escXml(sheet.name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`
    )
    .join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>${sheetsXml}</sheets></workbook>`;
}

function workbookRelsXml(sheetCount: number): string {
  const worksheetType =
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet";
  const rels = [];
  for (let i = 0; i < sheetCount; i += 1) {
    rels.push(
      `<Relationship Id="rId${i + 1}" Type="${worksheetType}" Target="worksheets/sheet${i + 1}.xml"/>`
    );
  }
  rels.push(
    `<Relationship Id="rId${sheetCount + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>`
  );
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${rels.join("")}</Relationships>`;
}

function contentTypesXml(sheetCount: number): string {
  const sheetType =
    "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml";
  const overrides = [
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
  ];
  for (let i = 0; i < sheetCount; i += 1) {
    overrides.push(
      `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="${sheetType}"/>`
    );
  }
  overrides.push(
    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
  );
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>${overrides.join("")}</Types>`;
}

function rootRelsXml(): string {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`;
}

const encoder = new TextEncoder();

function crc32(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i += 1) {
    crc ^= data[i];
    for (let k = 0; k < 8; k += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function dosDateTime(d = new Date()): { time: number; date: number } {
  const time = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1);
  const date =
    ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();
  return { time, date };
}

function zipBlob(files: { name: string; data: Uint8Array }[]): Blob {
  const parts: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;
  for (const file of files) {
    const name = encoder.encode(file.name);
    const crc = crc32(file.data);
    const { time, date } = dosDateTime();
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true);
    local.setUint16(6, 0, true);
    local.setUint16(8, 0, true);
    local.setUint16(10, time, true);
    local.setUint16(12, date, true);
    local.setUint32(14, crc, true);
    local.setUint32(18, file.data.length, true);
    local.setUint32(22, file.data.length, true);
    local.setUint16(26, name.length, true);
    local.setUint16(28, 0, true);
    parts.push(new Uint8Array(local.buffer), name, file.data);

    const cd = new DataView(new ArrayBuffer(46));
    cd.setUint32(0, 0x02014b50, true);
    cd.setUint16(4, 20, true);
    cd.setUint16(6, 20, true);
    cd.setUint16(8, 0, true);
    cd.setUint16(10, 0, true);
    cd.setUint16(12, time, true);
    cd.setUint16(14, date, true);
    cd.setUint32(16, crc, true);
    cd.setUint32(20, file.data.length, true);
    cd.setUint32(24, file.data.length, true);
    cd.setUint16(28, name.length, true);
    cd.setUint16(30, 0, true);
    cd.setUint16(32, 0, true);
    cd.setUint16(34, 0, true);
    cd.setUint16(36, 0, true);
    cd.setUint32(38, 0, true);
    cd.setUint32(42, offset, true);
    central.push(new Uint8Array(cd.buffer), name);
    offset += 30 + name.length + file.data.length;
  }

  let centralSize = 0;
  for (const part of central) centralSize += part.length;

  const eocd = new DataView(new ArrayBuffer(22));
  eocd.setUint32(0, 0x06054b50, true);
  eocd.setUint16(4, 0, true);
  eocd.setUint16(6, 0, true);
  eocd.setUint16(8, files.length, true);
  eocd.setUint16(10, files.length, true);
  eocd.setUint32(12, centralSize, true);
  eocd.setUint32(16, offset, true);
  eocd.setUint16(20, 0, true);

  const all = [...parts, ...central, new Uint8Array(eocd.buffer)];
  const total = all.reduce((n, part) => n + part.length, 0);
  const out = new Uint8Array(total);
  let pos = 0;
  for (const part of all) {
    out.set(part, pos);
    pos += part.length;
  }
  return new Blob([out.buffer], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

export function buildXlsx(sheets: XlsxSheet[]): Blob {
  const registry = buildRegistry(sheets);
  const files: { name: string; data: Uint8Array }[] = [
    { name: "[Content_Types].xml", data: encoder.encode(contentTypesXml(sheets.length)) },
    { name: "_rels/.rels", data: encoder.encode(rootRelsXml()) },
    { name: "xl/workbook.xml", data: encoder.encode(workbookXml(sheets)) },
    {
      name: "xl/_rels/workbook.xml.rels",
      data: encoder.encode(workbookRelsXml(sheets.length)),
    },
    { name: "xl/styles.xml", data: encoder.encode(stylesXml(registry)) },
  ];
  sheets.forEach((sheet, i) => {
    files.push({
      name: `xl/worksheets/sheet${i + 1}.xml`,
      data: encoder.encode(sheetXml(sheet, registry.styleIdOf)),
    });
  });
  return zipBlob(files);
}

export function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function euro2(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}