import { euro2, type XlsxCell, type XlsxSheet } from "./xlsx";

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

function money(parts: number[]): XlsxCell[] {
  return parts.map((n) => euro2(n));
}

/** Second sheet of an HD Resultaat file: the monthly drilldown. */
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
  const header: XlsxCell[] = ["Code", "Post", ...names, "Cumulatief"];
  const rows: XlsxCell[][] = [[`Resultaat ${label} ${data.year || year}`], header];
  const saldo = Array.from({ length: count }, () => 0);
  const hd = data.cashflow_1053?.stichting ? data.cashflow_1053 : null;

  if (hd && data.incoming_1053) {
    const parts = pad(data.incoming_1053.months, count);
    if (parts.some((n) => n !== 0)) {
      rows.push([
        String(data.incoming_1053.code ?? ""),
        data.incoming_1053.label || "Ontvangsten",
        ...money(parts),
        euro2(parts.reduce((sum, n) => sum + n, 0)),
      ]);
    }
  }
  for (const line of data.resultaat ?? []) {
    const parts = pad(line.months, count);
    const monthSum = parts.reduce((sum, n) => sum + n, 0);
    const cumul = parts.some((n) => n !== 0) ? monthSum : (line.amount ?? 0);
    rows.push([String(line.code ?? ""), line.label || "", ...money(parts), euro2(cumul)]);
    for (let i = 0; i < count; i += 1) saldo[i] += parts[i];
  }
  rows.push(["", hd ? "Saldo" : "Totaal", ...money(saldo), euro2(saldo.reduce((sum, n) => sum + n, 0))]);

  const meals = data.maaltijden;
  if (meals) {
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
    const cost = (foodAmt: number, eq: number): XlsxCell => (eq === 0 ? "" : euro2(-(foodAmt / eq)));
    const countRow = (name: string, parts: number[]) => {
      rows.push(["", name, ...money(parts), euro2(sum(parts))]);
    };
    rows.push([]);
    countRow("Aantal ontbijten", ont);
    countRow("Aantal koude maaltijden", koude);
    countRow("Aantal warme maaltijden", warme);
    countRow("Aantal warme maaltijden hd", warmHd);
    const equivMonths = ont.map((_, i) => equivalent(ont[i], koude[i], warme[i], warmHd[i]));
    const equivCumul = equivalent(sum(ont), sum(koude), sum(warme), sum(warmHd));
    rows.push(["", "Equivalent aantal tafelgenoten", ...equivMonths.map((n) => euro2(n)), euro2(equivCumul)]);
    rows.push([
      "",
      "Voedselkosten per tafelgenoot",
      ...equivMonths.map((eq, i) => cost(food[i], eq)),
      cost(foodCumul, equivCumul),
    ]);
  }

  if (hd) {
    const flow = (name: string, parts: number[]) => {
      rows.push(["", name, ...money(parts), euro2(parts.reduce((sum, n) => sum + n, 0))]);
    };
    const stock = (name: string, parts: number[]) => {
      rows.push(["", name, ...money(parts), ""]);
    };
    rows.push([]);
    stock("Beginsaldo", pad(hd.opening?.months, count));
    flow("Stichting de Oude Gracht", pad(hd.stichting?.months, count));
    flow("Overige inkomsten", pad(hd.inkomsten?.months, count));
    flow("Uitgaven", pad(hd.uitgaven?.months, count));
    flow("Resultaat", pad(hd.resultaat?.months, count));
    rows.push([]);
    stock("Banksaldo einde maand", pad(hd.banksaldo?.months, count));
  } else if (data.cashflow_1053) {
    const cash = data.cashflow_1053;
    const flow = (name: string, parts: number[]) => {
      rows.push(["", name, ...money(parts), euro2(parts.reduce((sum, n) => sum + n, 0))]);
    };
    const stock = (name: string, parts: number[]) => {
      rows.push(["", name, ...money(parts), ""]);
    };
    rows.push([]);
    stock("Beginsaldo", pad(cash.opening?.months, count));
    flow("Overige mutaties", pad(cash.other?.months, count));
    flow("Resultaat", saldo);
    rows.push([]);
    stock("Banksaldo einde maand", pad(cash.banksaldo?.months, count));
  }

  return {
    name: "Maandelijks",
    rows,
    widths: [12, 36, ...names.map(() => 14), 14],
  };
}
