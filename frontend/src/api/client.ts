// Thin fetch wrapper. Everything the UI does goes through the REST API so a
// mobile client can reuse the exact same endpoints later.

import type {
  AppSettings,
  BrowserCheck,
  ChapterRead,
  ChapterStatus,
  ChapterSummary,
  ExportFormat,
  FollowCheckResult,
  FollowStatus,
  GlossaryTerm,
  Job,
  JobStatus,
  NovelDetail,
  NovelSummary,
  Paged,
  Preview,
  SettingsPatch,
  SourceInfo,
} from "./types";

const BASE = "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      if (body?.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // response had no JSON body; keep statusText
    }
    throw new ApiError(detail, resp.status);
  }

  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PATCH",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export interface Health {
  status: string;
  version: string;
}

export const getHealth = () => api.get<Health>("/health");

// --- library ---------------------------------------------------------------

export const listNovels = (params: { limit?: number; offset?: number; followed?: boolean } = {}) => {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  if (params.followed !== undefined) query.set("followed", String(params.followed));
  const suffix = query.toString();
  return api.get<Paged<NovelSummary>>(`/novels${suffix ? `?${suffix}` : ""}`);
};

export const getNovel = (id: number) => api.get<NovelDetail>(`/novels/${id}`);

export const updateNovel = (
  id: number,
  changes: Partial<Pick<NovelDetail, "title" | "author" | "followed" | "translate_enabled">>,
) => api.patch<NovelDetail>(`/novels/${id}`, changes);

export const deleteNovel = (id: number) => api.delete<void>(`/novels/${id}`);

export const listChapters = (
  id: number,
  params: { limit?: number; offset?: number; status?: ChapterStatus } = {},
) => {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  if (params.status) query.set("status", params.status);
  const suffix = query.toString();
  return api.get<Paged<ChapterSummary>>(`/novels/${id}/chapters${suffix ? `?${suffix}` : ""}`);
};

/** Download URL for an export. Used as a plain link so the browser saves it. */
export const exportUrl = (
  id: number,
  format: ExportFormat,
  options: { translated?: boolean; volumeSize?: number } = {},
) => {
  const query = new URLSearchParams({ format });
  if (options.translated) query.set("translated", "true");
  if (options.volumeSize) query.set("volume_size", String(options.volumeSize));
  return `${BASE}/novels/${id}/export?${query.toString()}`;
};

// --- sources and preview ---------------------------------------------------

export const listSources = () => api.get<SourceInfo[]>("/sources");

export const previewUrl = (url: string) => api.post<Preview>("/preview", { url });

// --- jobs ------------------------------------------------------------------

export const listJobs = (params: { limit?: number; status?: JobStatus } = {}) => {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.status) query.set("status", params.status);
  const suffix = query.toString();
  return api.get<Paged<Job>>(`/jobs${suffix ? `?${suffix}` : ""}`);
};

export const getJob = (id: number) => api.get<Job>(`/jobs/${id}`);

export const startCrawl = (url: string) => api.post<Job>("/jobs", { url });

export const startUpdate = (novelId: number) => api.post<Job>(`/novels/${novelId}/update`);

export const pauseJob = (id: number) => api.post<Job>(`/jobs/${id}/pause`);
export const resumeJob = (id: number) => api.post<Job>(`/jobs/${id}/resume`);
export const cancelJob = (id: number) => api.post<Job>(`/jobs/${id}/cancel`);

export const jobEventsUrl = (id: number) => `${BASE}/jobs/${id}/events`;

// --- settings --------------------------------------------------------------

export const getSettings = () => api.get<AppSettings>("/settings");

export const saveSettings = (changes: SettingsPatch) =>
  request<AppSettings>("/settings", { method: "PUT", body: JSON.stringify(changes) });

export const deleteCookie = (domain: string) =>
  api.delete<AppSettings>(`/settings/cookies/${encodeURIComponent(domain)}`);

export const checkBrowser = () => api.post<BrowserCheck>("/settings/browser-check");

// --- follow / auto update --------------------------------------------------

export const getFollowStatus = () => api.get<FollowStatus>("/follow/status");

export const checkFollowNow = () => api.post<FollowCheckResult>("/follow/check-now");

/** Clear the "new chapters" badge once the user has looked at the novel. */
export const markNovelSeen = (novelId: number) => api.post<void>(`/follow/${novelId}/seen`);

// --- translation -----------------------------------------------------------

export const listGlossary = (novelId: number) =>
  api.get<GlossaryTerm[]>(`/novels/${novelId}/glossary`);

export const addGlossaryTerm = (
  novelId: number,
  term: { source: string; target: string; note?: string },
) => api.post<GlossaryTerm>(`/novels/${novelId}/glossary`, term);

export const deleteGlossaryTerm = (novelId: number, termId: number) =>
  api.delete<void>(`/novels/${novelId}/glossary/${termId}`);

export const startTranslation = (novelId: number, force = false) =>
  api.post<Job>(`/novels/${novelId}/translate`, { force });

// --- reader ----------------------------------------------------------------

export const readChapter = (novelId: number, number: number, translated = false) =>
  api.get<ChapterRead>(
    `/novels/${novelId}/chapters/${number}${translated ? "?translated=true" : ""}`,
  );

export const saveProgress = (novelId: number, chapter: number) =>
  request<NovelDetail>(`/novels/${novelId}/progress`, {
    method: "PUT",
    body: JSON.stringify({ chapter }),
  });
