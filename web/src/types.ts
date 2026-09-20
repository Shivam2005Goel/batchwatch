export type Verdict = "FLAGGED" | "UNCERTAIN" | "NO_MATCH" | "UNREADABLE" | "SKIPPED";
export type Tone = "red" | "amber" | "green" | "grey";
export type Lang = "en" | "hi" | "ta";

export interface NsqRow {
  drug_name: string;
  generic: string;
  strength: string;
  manufacturer_raw: string;
  manufacturer: string;
  batch_raw: string;
  batch_norm: string;
  batch_skeleton: string;
  mfg_date: string;
  exp_date: string;
  failure_reason: string;
  failure_class: string;
  severity: string;
  lab: string;
  alert_month: string;
  source_url: string;
  synthetic?: boolean;
  _score?: number;
  _matched_on?: string;
}

export interface Extracted {
  drug_name: string;
  manufacturer: string;
  batch: string;
  mfg_date: string;
  exp_date: string;
  confidence: number;
  legible: boolean;
  notes: string;
  source: string;
  raw_text?: string;
  cached?: boolean;
}

export interface ScanResult {
  verdict: Verdict;
  tone: Tone;
  headline: string;
  score?: number;
  severity?: string;
  advice?: Record<Lang, string>;
  reason: string;
  adjudicated?: boolean;
  match: NsqRow | null;
  candidates?: { score: number; batch: string; drug_name: string; alert_month: string }[];
  expired?: boolean;
  expiry_note?: string;
  disclaimer: string;
  extracted?: Extracted;
  corpus_rows?: number;
}

export interface ShelfItem {
  item_id: string;
  drug_name: string;
  manufacturer: string;
  batch_raw: string;
  batch_norm: string;
  mfg_date: string;
  exp_date: string;
  nickname: string;
  added_at: string;
  last_verdict: Verdict;
  verdict?: Verdict;
  tone?: Tone;
  severity?: string;
  expired?: boolean;
  match?: NsqRow | null;
}

export interface Alert {
  alert_id: string;
  item_id: string;
  drug_name: string;
  batch_raw: string;
  batch_norm: string;
  severity: string;
  failure_class: string;
  failure_reason: string;
  alert_month: string;
  source_url: string;
  manufacturer: string;
  score: number;
  verdict: Verdict;
  created_at: string;
  read: boolean;
}

export interface Stats {
  rows: number;
  distinct_batches: number;
  distinct_molecules: number;
  alert_months: number;
  earliest_alert_month: string;
  latest_alert_month: string;
  severities: Record<string, number>;
  synthetic_rows: number;
  corpus_is_synthetic: boolean;
  disclaimer: string;
}

export interface PharmacyRow {
  line: number;
  input: Record<string, string>;
  verdict: Verdict;
  tone: Tone;
  severity?: string;
  score?: number;
  reason: string;
  match?: NsqRow | null;
  expired?: boolean;
}

export interface PharmacyJob {
  job_id: string;
  created_at: string;
  rows: number;
  counts: Record<string, number>;
  results: PharmacyRow[];
  corpus_rows: number;
  disclaimer: string;
}
