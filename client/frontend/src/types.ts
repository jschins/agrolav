export interface PersonInfo {
  person_name: string;
}

export interface MatrixResponse {
  categories: string[];
  people: PersonInfo[];
  cells: Record<string, Record<string, string>>;
  footers?: { balance: string; last_booked: string };
  table_header_terms?: Record<string, string>;
}

export interface RefreshPersonResult {
  person_name: string;
  skipped: boolean;
  reason?: string;
  transaction_count?: number;
  date_from?: string;
  date_to?: string;
  warnings?: string[];
  account_errors?: string[];
  authorization_url?: string | null;
  new_year?: boolean;
}

export interface RefreshResponse {
  matrix: MatrixResponse;
  results: RefreshPersonResult[];
  warnings: string[];
}

export interface TypeRule {
  type: string;
  category: string;
}

export interface SettingsResponse {
  categories: string[];
  people: PersonInfo[];
  general: Record<string, string[]>;
  personal: Record<string, Record<string, string[]>>;
  valid_category_codes: number[];
  remainder_category: string;
  typerules: TypeRule[];
  table_header_terms?: Record<string, string>;
}

export type Transaction = Record<string, unknown>;

export interface TransactionsResponse {
  person: string;
  category: string;
  columns: string[];
  transactions: Transaction[];
  description_modified_ids: string[];
  category_modified_ids: string[];
  keywords: string[];
  abbreviations: Record<string, string>;
  table_header_terms?: Record<string, string>;
  valid_category_codes: number[];
  remainder_category: string;
}

export interface TermsUpdateResponse {
  group: string;
  category: string;
  terms: string[];
  matrix?: MatrixResponse;
}

export interface AddTermResponse {
  group: string;
  category: string;
  term: string;
  terms: string[];
  matrix: MatrixResponse;
}

export interface CatalogCategory {
  category_id?: number | null;
  local_code: number;
  label: string;
  is_remainder: boolean;
}

export interface CatalogResponse {
  country: string;
  country_id?: number | null;
  remainder_id?: number | null;
  center?: string;
  digits?: number;
  categories: CatalogCategory[];
}

export interface ModificationResponse {
  person: string;
  transaction?: Transaction;
  matrix?: MatrixResponse;
}

export interface TransactionSplitLine {
  id?: string | null;
  description: string;
  amount: string;
}

export interface TransactionSplitResponse {
  person: string;
  year?: string;
  id: string;
  original_amount: string;
  description: string;
  date?: string;
  name?: string;
  iban?: string;
  type?: string;
  category?: number;
  lines: TransactionSplitLine[];
}
