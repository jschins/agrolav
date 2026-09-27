export interface XlsxStyled {
  value: string | number;
  style: number;
}

export type XlsxCell = string | number | XlsxStyled;

export interface XlsxSheet {
  name: string;
  rows: XlsxCell[][];
  widths?: number[];
  merges?: string[];
  /** Fit the sheet onto one printed page, landscape. */
  fitPage?: boolean;
  rowHeights?: (number | undefined)[];
}

/** Styles that mirror the Resultaat window: cream page, white cards, #ffecbc headings. */
export const RESULT_STYLE = {
  page: 2,
  title: 3,
  heading: 4,
  head: 5,
  code: 6,
  text: 7,
  amount: 8,
  total: 9,
  totalAmount: 10,
  strong: 11,
  strongAmount: 12,
  alert: 13,
  alertAmount: 14,
} as const;

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

function cellValue(cell: XlsxCell): { value: string | number; style?: number } {
  if (typeof cell === "object" && cell !== null) return cell;
  return { value: cell };
}

function sheetXml(sheet: XlsxSheet): string {
  const rowsXml = sheet.rows
    .map((row, ri) => {
      if (row.length === 0) return "";
      const r = ri + 1;
      const height = sheet.rowHeights?.[ri];
      const cellsXml = row
        .map((cell, ci) => {
          const ref = `${colLetter(ci)}${r}`;
          const { value, style } = cellValue(cell);
          const s = style != null ? ` s="${style}"` : typeof value === "number" ? ` s="1"` : "";
          if (typeof value === "number") {
            return `<c r="${ref}"${s}><v>${value}</v></c>`;
          }
          return `<c r="${ref}"${s} t="inlineStr"><is><t>${escXml(String(value))}</t></is></c>`;
        })
        .join("");
      const ht = height ? ` ht="${height}" customHeight="1"` : "";
      return `<row r="${r}"${ht}>${cellsXml}</row>`;
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
  const merges = sheet.merges ?? [];
  const mergeXml =
    merges.length > 0
      ? `<mergeCells count="${merges.length}">${merges
          .map((ref) => `<mergeCell ref="${escXml(ref)}"/>`)
          .join("")}</mergeCells>`
      : "";
  const sheetPr = sheet.fitPage ? `<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>` : "";
  const views = sheet.fitPage
    ? `<sheetViews><sheetView workbookViewId="0" showGridLines="0"/></sheetViews>`
    : "";
  const setupXml = sheet.fitPage
    ? `<pageMargins left="0.4" right="0.4" top="0.5" bottom="0.4" header="0.2" footer="0.2"/><pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="1"/>`
    : "";
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">${sheetPr}<dimension ref="A1:${lastCol}${Math.max(1, sheet.rows.length)}"/>${views}${colsXml}<sheetData>${rowsXml}</sheetData>${mergeXml}${setupXml}</worksheet>`;
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

function fontXml(size: number, color: string, bold = false): string {
  const b = bold ? "<b/>" : "";
  return `<font>${b}<sz val="${size}"/><color rgb="${color}"/><name val="Calibri"/><family val="2"/></font>`;
}

function fillXml(rgb: string): string {
  return `<fill><patternFill patternType="solid"><fgColor rgb="${rgb}"/><bgColor indexed="64"/></patternFill></fill>`;
}

function borderXml(top?: string, bottom?: string): string {
  const edge = (side: string, color?: string) =>
    color ? `<${side} style="${color === "2A5A8C" ? "medium" : "thin"}"><color rgb="FF${color}"/></${side}>` : `<${side}/>`;
  return `<border>${edge("left")}${edge("right")}${edge("top", top)}${edge("bottom", bottom)}<diagonal/></border>`;
}

function xfXml(
  fontId: number,
  fillId: number,
  borderId: number,
  numFmtId = 0,
  align?: "right"
): string {
  const alignXml = align ? `<alignment horizontal="${align}"/>` : "";
  return `<xf numFmtId="${numFmtId}" fontId="${fontId}" fillId="${fillId}" borderId="${borderId}" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">${alignXml}</xf>`;
}

function stylesXml(): string {
  const fonts = [
    fontXml(11, "FF1A1A1A"),
    fontXml(11, "FF1A1A1A", true),
    fontXml(11, "FF666666"),
    fontXml(11, "FFB91C1C", true),
    fontXml(16, "FF1A1A1A", true),
  ].join("");
  const fills = [fillXml("FFFBF6E3"), fillXml("FFFFFFFF"), fillXml("FFFFECBC")].join("");
  const borders = [
    borderXml(),
    borderXml(undefined, "EEF0F3"),
    borderXml("2A5A8C"),
    borderXml(undefined, "E0E3E8"),
  ].join("");
  // 0 plain, 1 legacy number, then the Resultaat window styles.
  const xfs = [
    `<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>`,
    `<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>`,
    xfXml(0, 2, 0),
    xfXml(4, 2, 0),
    xfXml(1, 4, 3),
    xfXml(1, 3, 1),
    xfXml(2, 3, 1),
    xfXml(0, 3, 1),
    xfXml(0, 3, 1, 165, "right"),
    xfXml(1, 3, 2),
    xfXml(1, 3, 2, 165, "right"),
    xfXml(1, 3, 1),
    xfXml(1, 3, 1, 165, "right"),
    xfXml(3, 3, 1),
    xfXml(3, 3, 1, 165, "right"),
  ].join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="1"><numFmt numFmtId="165" formatCode="#,##0"/></numFmts><fonts count="5">${fonts}</fonts><fills count="5"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>${fills}</fills><borders count="4">${borders}</borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="${15}">${xfs}</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`;
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
  const files: { name: string; data: Uint8Array }[] = [
    { name: "[Content_Types].xml", data: encoder.encode(contentTypesXml(sheets.length)) },
    { name: "_rels/.rels", data: encoder.encode(rootRelsXml()) },
    { name: "xl/workbook.xml", data: encoder.encode(workbookXml(sheets)) },
    {
      name: "xl/_rels/workbook.xml.rels",
      data: encoder.encode(workbookRelsXml(sheets.length)),
    },
    { name: "xl/styles.xml", data: encoder.encode(stylesXml()) },
  ];
  sheets.forEach((sheet, i) => {
    files.push({
      name: `xl/worksheets/sheet${i + 1}.xml`,
      data: encoder.encode(sheetXml(sheet)),
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