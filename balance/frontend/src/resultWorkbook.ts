import type { BalanceLine, BalanceSheet } from "./types";
import { buildXlsx, euro2, RESULT_STYLE, type XlsxCell, type XlsxSheet } from "./xlsx";

function paint(value: string | number, style: number): XlsxCell {
  return { value, style };
}

/** One-page Resultaat workbook. The unit Export knob and Export zip both call this. */
export function resultSheet(data: BalanceSheet, label: string): XlsxSheet {
  const title = `Resultaat${label ? ` ${label}` : ""} ${data.year}`;
  const S = RESULT_STYLE;
  const page = () => paint("", S.page);
  const rows: XlsxCell[][] = [];
  const merges: string[] = [];
  const heights: (number | undefined)[] = [];
  const push = (row: XlsxCell[], height?: number) => {
    rows.push(row);
    heights.push(height);
  };
  const at = () => rows.length + 1;

  push(
    [paint(title, S.title), paint("", S.title), paint("", S.title), paint("", S.title), paint("", S.title), paint("", S.title), paint("", S.title)],
    24
  );
  merges.push("A1:G1");
  push([page(), page(), page(), page(), page(), page(), page()], 10);

  const headRow = at();
  push(
    [
      paint("Uitgaven", S.heading),
      paint("", S.heading),
      paint("", S.heading),
      page(),
      paint("Inkomsten", S.heading),
      paint("", S.heading),
      paint("", S.heading),
    ],
    22
  );
  merges.push(`A${headRow}:C${headRow}`, `E${headRow}:G${headRow}`);
  push([
    paint("Code", S.head),
    paint("Post", S.head),
    paint("Bedrag", S.head),
    page(),
    paint("Code", S.head),
    paint("Post", S.head),
    paint("Bedrag", S.head),
  ]);

  const body = (line: BalanceLine | undefined): XlsxCell[] =>
    line
      ? [paint(String(line.code), S.code), paint(line.label, S.text), paint(euro2(line.amount), S.amount)]
      : [paint("", S.text), paint("", S.text), paint("", S.text)];
  const count = Math.max(data.activa.length, data.passiva.length);
  for (let i = 0; i < count; i += 1) {
    push([...body(data.activa[i]), page(), ...body(data.passiva[i])]);
  }

  const totalRow = at();
  push([
    paint("Totaal Uitgaven", S.total),
    paint("", S.total),
    paint(euro2(data.total_activa), S.totalAmount),
    page(),
    paint("Totaal Inkomsten", S.total),
    paint("", S.total),
    paint(euro2(data.total_passiva), S.totalAmount),
  ]);
  merges.push(`A${totalRow}:B${totalRow}`, `E${totalRow}:F${totalRow}`);

  if (data.cash) {
    push([page(), page(), page(), page(), page(), page(), page()], 14);
    const balansRow = at();
    push(
      [paint("Balans", S.heading), paint("", S.heading), paint("", S.heading), page(), page(), page(), page()],
      22
    );
    merges.push(`A${balansRow}:C${balansRow}`);
    for (const row of data.cash.rows) {
      if (row.gap) {
        push([page(), page(), page(), page(), page(), page(), page()], 10);
        continue;
      }
      const labelStyle = row.alert ? S.alert : row.strong ? S.strong : S.text;
      const amountStyle = row.alert ? S.alertAmount : row.strong ? S.strongAmount : S.amount;
      const lineRow = at();
      push([
        paint(row.label, labelStyle),
        paint("", labelStyle),
        paint(euro2(row.amount ?? 0), amountStyle),
        page(),
        page(),
        page(),
        page(),
      ]);
      merges.push(`A${lineRow}:B${lineRow}`);
    }
  }

  return {
    name: "Resultaat",
    rows,
    widths: [12, 36, 14, 3, 12, 36, 14],
    merges,
    fitPage: true,
    rowHeights: heights,
  };
}

export function unitResultWorkbook(data: BalanceSheet, label: string): Blob {
  return buildXlsx([resultSheet(data, label.trim())]);
}
