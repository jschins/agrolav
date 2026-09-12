export interface BalanceLine {
  category_id: number;
  code: number;
  label: string;
  amount: number;
  source: string;
  unchanged?: boolean;
  role?: string;
}

export interface PlugDebug {
  opening: string;
  calculated: string;
  equal: boolean;
}

export interface AfschrijvingJournal {
  journal_id: number;
  date: string;
  category_from: number;
  category_to: number;
  from_label: string;
  to_label: string;
  amount: number;
  description: string;
}

export interface Afschrijvingen {
  from_codes: number[];
  journals: AfschrijvingJournal[];
}

export interface SubadministratieSheet {
  local_codes: number[];
  rows: SubadministratieRow[];
}

export interface BalanceSheet {
  year: number;
  as_of?: string | null;
  activa: BalanceLine[];
  passiva: BalanceLine[];
  total_activa: number;
  total_passiva: number;
  balanced: boolean;
  subadministratie?: SubadministratieSheet;
  afschrijvingen?: Afschrijvingen;
  plug_debug?: PlugDebug;
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

export interface DatesResponse {
  year: number;
  dates: string[];
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
  remainder_id: number;
}

export interface ResultRow {
  code: number;
  label: string;
  amount: number;
}

export interface ResultResponse {
  year: number;
  rows: ResultRow[];
  total: number;
}

export interface SubadministratieRow {
  local_code: number;
  name: string;
  amount: number;
}

export interface SubadministratieResponse {
  country_id: number;
  local_code: number | null;
  rows: SubadministratieRow[];
}

export interface CategoryTransactionRow {
  name: string;
  amount: number;
}

export interface CategoryTransactionsResponse {
  country_id: number;
  local_code: number;
  rows: CategoryTransactionRow[];
}

export interface PostPopupResponse {
  local_code: number;
  people: SubadministratieRow[];
  journals: AfschrijvingJournal[];
}
