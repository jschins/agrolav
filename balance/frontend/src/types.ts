export interface BalanceLine {
  category_id: number;
  code: number;
  label: string;
  amount: number;
  source: string;
}

export interface BalanceSheet {
  year: number;
  activa: BalanceLine[];
  passiva: BalanceLine[];
  total_activa: number;
  total_passiva: number;
  balanced: boolean;
}

export interface CategoryInfo {
  category_id: number;
  code: number;
  label: string;
  side: "activa" | "passiva";
  account_id: number | null;
  iban?: string;
  account_balance?: number;
}

export interface YearsResponse {
  years: number[];
}

export interface JournalRow {
  journal_id: number;
  year: number;
  date: string;
  category_from: number;
  category_to: number;
  amount: number;
  description: string;
  from_label: string;
  to_label: string;
}

export interface JournalResponse {
  year: number;
  rows: JournalRow[];
}

export interface CategoriesResponse {
  categories: CategoryInfo[];
}
