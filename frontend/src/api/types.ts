// Mirrors the backend schemas in app/api/schemas.py.

export type Lang = "vi" | "zh";
export type NovelStatus = "unknown" | "ongoing" | "completed";
export type ChapterStatus = "pending" | "done" | "failed" | "skipped_vip";
export type JobType = "crawl" | "update" | "translate" | "export";
export type JobStatus =
  | "queued"
  | "running"
  | "paused"
  | "done"
  | "failed"
  | "cancelled";

export interface NovelSummary {
  id: number;
  source: string;
  source_url: string;
  title: string;
  author: string | null;
  cover_url: string | null;
  lang: Lang;
  status: NovelStatus;
  translate_enabled: boolean;
  followed: boolean;
  last_read_chapter: number | null;
  created_at: string;
  updated_at: string;
}

export interface NovelDetail extends NovelSummary {
  description: string | null;
  genres: string[];
  last_checked_at: string | null;
  chapter_count: number;
  chapters_done: number;
  chapters_pending: number;
  chapters_failed: number;
  chapters_skipped: number;
  disk_bytes: number;
}

export interface ChapterSummary {
  id: number;
  number: number;
  title: string;
  volume: string | null;
  status: ChapterStatus;
  char_count: number;
  has_translation: boolean;
  fetched_at: string | null;
}

export interface Job {
  id: number;
  type: JobType;
  status: JobStatus;
  novel_id: number | null;
  total: number;
  done: number;
  failed: number;
  skipped: number;
  error: string | null;
  params: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  processed: number;
  percent: number;
}

export interface SourceInfo {
  key: string;
  name: string;
  domains: string[];
  lang: Lang;
  needs_browser: boolean;
}

export interface Preview {
  source: string;
  source_name: string;
  url: string;
  title: string;
  author: string | null;
  cover_url: string | null;
  description: string | null;
  genres: string[];
  status: NovelStatus;
  lang: Lang;
  novel_id: number | null;
}

export interface Paged<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface AppSettings {
  proxy: string | null;
  browser_enabled: boolean;
  per_domain_delay: number;
  per_domain_concurrency: number;
  request_timeout: number;
  chapter_retry_limit: number;
  /** Cookie header strings keyed by domain. */
  cookies: Record<string, string>;
  /** Provider -> masked key, or null when unset. */
  api_keys: Record<string, string | null>;
}

export type SettingsPatch = Partial<
  Omit<AppSettings, "api_keys"> & { api_keys: Record<string, string | null> }
>;

export interface BrowserCheck {
  available: boolean;
  detail: string;
}

export interface GlossaryTerm {
  id: number;
  source: string;
  target: string;
  note: string | null;
}

export interface ChapterRead {
  number: number;
  title: string;
  text: string;
  translated: boolean;
  has_translation: boolean;
  prev_number: number | null;
  next_number: number | null;
  novel_id: number;
  novel_title: string;
}

/** One frame from the job event stream. */
export interface ProgressEvent {
  job_id: number;
  status: JobStatus;
  total: number;
  done: number;
  failed: number;
  skipped: number;
  message: string | null;
  chapter: number | null;
  processed: number;
  percent: number;
}

export type ExportFormat = "epub" | "txt" | "json";
