import { euro2, MONTHLY_STYLE, RESULT_STYLE, type XlsxCell, type XlsxSheet } from "./xlsx";

const MONTHS = [
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

interface Line {
  code?: string | number;
  label?: string;
  months?: number[];
  amount?: number;
}

interface MealCounts {
  ontbijten?: number[];
  koude?: number[];
  warme?: number[];
  warm_hd?: number[];
}

interface MonthlyPayload {
  year: number;
  month_count?: number;
  incoming_1053?: Line | null;
  resultaat?: Line[];
  maaltijden?: MealCounts | null;
  cashflow_1053?: {
    opening?: Line;
    other?: Line;
    stichting?: Line;
    inkomsten?: Line;
    uitgaven?: Line;
    resultaat?: Line;
    banksaldo?: Line;
  } | null;
}

function monthCountOf(data: MonthlyPayload): number {
  const now = new Date();
  let cap = 12;
  if (data.year > now.getFullYear()) cap = 0;
  else if (data.year === now.getFullYear()) cap = now.getMonth() + 1;
  const reported = data.month_count;
  if (typeof reported === "number" && reported >= 0 && reported <= 12) {
    return Math.min(reported, cap);
  }
  return cap;
}

function pad(raw: number[] | undefined, count: number): number[] {
  const next = [...(raw ?? [])];
  while (next.length < count) next.push(0);
  return next.slice(0, count);
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

function paint(value: string | number, style: number): XlsxCell {
  return { value, style };
}

/** Second sheet: page title, then the Resultaat, Balans, and meal tables. */
export async function hdMonthlySheet(year: number, label: string): Promise<XlsxSheet> {
  const resp = await fetch(`/api/export-resultaat?year=${encodeURIComponent(String(year))}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || `${resp.status} ${resp.statusText}`);
  }
  const data = (await resp.json()) as MonthlyPayload;
  const count = monthCountOf(data);
  const names = MONTHS.slice(0, count);
  const cols = 2 + count + 1;
  const last = colLetter(cols - 1);
  const S = RESULT_STYLE;
  const M = MONTHLY_STYLE;
  const rows: XlsxCell[][] = [];
  const merges: string[] = [];
  const heights: (number | undefined)[] = [];
  const push = (row: XlsxCell[], height?: number) => {
    rows.push(row);
    heights.push(height);
  };
  const at = () => rows.length + 1;
  const fill = (style: number) => Array.from({ length: cols }, () => paint("", style));
  const span = (text: string, style: number, height: number) => {
    const n = at();
    const row = fill(style);
    row[0] = paint(text, style);
    push(row, height);
    merges.push(`A${n}:${last}${n}`);
  };
  const header = () => {
    push([
      paint("Code", S.head),
      paint("Post", S.head),
      ...names.map((name) => paint(name, S.head)),
      paint("Cumulatief", S.head),
    ]);
  };
  const moneyRow = (
    code: string,
    name: string,
    parts: number[],
    cumul: number | "",
    kind: "body" | "total" | "strong" = "body"
  ) => {
    const labelStyle = kind === "total" ? S.total : kind === "strong" ? S.strong : S.text;
    const codeStyle = kind === "total" ? S.total : kind === "strong" ? S.strong : S.code;
    const amountStyle = kind === "total" ? M.totalAmount : kind === "strong" ? M.strongAmount : M.amount;
    push([
      paint(code, codeStyle),
      paint(name, labelStyle),
      ...parts.map((n) => paint(euro2(n), amountStyle)),
      cumul === "" ? paint("", labelStyle) : paint(euro2(cumul), amountStyle),
    ]);
  };
  const countRow = (name: string, parts: number[]) => {
    const total = parts.reduce((sum, n) => sum + n, 0);
    push([
      paint("", S.code),
      paint(name, S.text),
      ...parts.map((n) => paint(euro2(n), S.amount)),
      paint(euro2(total), S.amount),
    ]);
  };

  const pageTitle = [label.trim(), String(data.year || year)].filter(Boolean).join(" ");
  span(pageTitle, S.title, 24);
  push(fill(S.page), 10);

  const saldo = Array.from({ length: count }, () => 0);
  const hd = data.cashflow_1053?.stichting ? data.cashflow_1053 : null;
  span("Resultaat", S.heading, 22);
  header();
  if (hd && data.incoming_1053) {
    const parts = pad(data.incoming_1053.months, count);
    if (parts.some((n) => n !== 0)) {
      moneyRow(
        String(data.incoming_1053.code ?? ""),
        data.incoming_1053.label || "Ontvangsten",
        parts,
        parts.reduce((sum, n) => sum + n, 0)
      );
    }
  }
  for (const line of data.resultaat ?? []) {
    const parts = pad(line.months, count);
    const monthSum = parts.reduce((sum, n) => sum + n, 0);
    const cumul = parts.some((n) => n !== 0) ? monthSum : (line.amount ?? 0);
    moneyRow(String(line.code ?? ""), line.label || "", parts, cumul);
    for (let i = 0; i < count; i += 1) saldo[i] += parts[i];
  }
  moneyRow("", hd ? "Saldo" : "Totaal", saldo, saldo.reduce((sum, n) => sum + n, 0), "total");

  if (hd || data.cashflow_1053) {
    push(fill(M.rule), 8);
    span("Balans", S.heading, 22);
    header();
    const flow = (name: string, parts: number[]) => {
      moneyRow("", name, parts, parts.reduce((sum, n) => sum + n, 0));
    };
    const stock = (name: string, parts: number[], kind: "body" | "strong" = "body") => {
      moneyRow("", name, parts, "", kind);
    };
    if (hd) {
      stock("Beginsaldo", pad(hd.opening?.months, count));
      flow("Stichting de Oude Gracht", pad(hd.stichting?.months, count));
      flow("Overige inkomsten", pad(hd.inkomsten?.months, count));
      flow("Uitgaven", pad(hd.uitgaven?.months, count));
      flow("Resultaat", pad(hd.resultaat?.months, count));
      push(fill(S.page), 8);
      stock("Banksaldo einde maand", pad(hd.banksaldo?.months, count), "strong");
    } else if (data.cashflow_1053) {
      const cash = data.cashflow_1053;
      stock("Beginsaldo", pad(cash.opening?.months, count));
      flow("Overige mutaties", pad(cash.other?.months, count));
      flow("Resultaat", saldo);
      push(fill(S.page), 8);
      stock("Banksaldo einde maand", pad(cash.banksaldo?.months, count), "strong");
    }
  }

  const meals = data.maaltijden;
  if (meals) {
    push(fill(M.ruleHeavy), 10);
    span("Appendix: Maaltijdenoverzicht", S.heading, 22);
    header();
    const ont = pad(meals.ontbijten, count);
    const koude = pad(meals.koude, count);
    const warme = pad(meals.warme, count);
    const warmHd = pad(meals.warm_hd, count);
    const foodLine = (data.resultaat ?? []).find((line) => Number(line.code) === 3035);
    const food = pad(foodLine?.months, count);
    const foodCumul = food.some((n) => n !== 0)
      ? food.reduce((sum, n) => sum + n, 0)
      : (foodLine?.amount ?? 0);
    const sum = (parts: number[]) => parts.reduce((total, n) => total + n, 0);
    const equivalent = (o: number, k: number, w: number, wh: number) => (o + 2 * k + 3 * w + 3 * wh) / 6;
    countRow("Aantal ontbijten", ont);
    countRow("Aantal koude maaltijden", koude);
    countRow("Aantal warme maaltijden", warme);
    countRow("Aantal warme maaltijden hd", warmHd);
    const equivMonths = ont.map((_, i) => equivalent(ont[i], koude[i], warme[i], warmHd[i]));
    const equivCumul = equivalent(sum(ont), sum(koude), sum(warme), sum(warmHd));
    moneyRow("", "Equivalent aantal tafelgenoten", equivMonths, equivCumul);
    const cost = (foodAmt: number, eq: number): number | "" => (eq === 0 ? "" : euro2(-(foodAmt / eq)));
    push([
      paint("", S.code),
      paint("Voedselkosten per tafelgenoot", S.text),
      ...equivMonths.map((eq, i) => {
        const value = cost(food[i], eq);
        return value === "" ? paint("", S.text) : paint(value, M.amount);
      }),
      (() => {
        const value = cost(foodCumul, equivCumul);
        return value === "" ? paint("", S.text) : paint(value, M.amount);
      })(),
    ]);
  }

  return {
    name: "Maandelijks",
    rows,
    widths: [12, 36, ...names.map(() => 14), 14],
    merges,
    hideGrid: true,
    rowHeights: heights,
  };
}
