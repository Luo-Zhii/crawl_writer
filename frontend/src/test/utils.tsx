import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

/** Render a page with the providers it expects, and no retries or caching. */
export function renderPage(ui: ReactElement, { route = "/" } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });

  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

type Handler = (url: string, init?: RequestInit) => unknown;

/**
 * Stub `fetch` with a path -> payload map.
 *
 * Keys are matched as substrings of the request URL, so "/api/novels" covers
 * the query string the client appends.
 */
export function stubFetch(routes: Record<string, unknown | Handler>) {
  const calls: { url: string; method: string }[] = [];

  const impl = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, method: init?.method ?? "GET" });

    const match = Object.keys(routes)
      // Longest key first so "/api/novels/1" beats "/api/novels".
      .sort((a, b) => b.length - a.length)
      .find((key) => url.includes(key));

    if (match === undefined) {
      return new Response(JSON.stringify({ detail: `no stub for ${url}` }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }

    const entry = routes[match];
    const payload = typeof entry === "function" ? (entry as Handler)(url, init) : entry;

    if (payload instanceof Response) return payload;

    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  globalThis.fetch = impl as typeof fetch;
  return { calls };
}

export function errorResponse(status: number, detail: string) {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export const paged = <T,>(items: T[]) => ({
  items,
  total: items.length,
  limit: 100,
  offset: 0,
});

export const novel = (overrides: Record<string, unknown> = {}) => ({
  id: 1,
  source: "truyenhoan",
  source_url: "https://truyenhoan.com/kiem-khach-vo-danh.31415/",
  title: "Kiếm Khách Vô Danh",
  author: "Mộng Trung Nhân",
  cover_url: null,
  lang: "vi",
  status: "ongoing",
  translate_enabled: false,
  followed: false,
  created_at: "2026-10-14T10:00:00Z",
  updated_at: "2026-10-14T12:00:00Z",
  ...overrides,
});

export const novelDetail = (overrides: Record<string, unknown> = {}) => ({
  ...novel(),
  description: "Một kiếm khách không tên.",
  genres: ["Tiên Hiệp"],
  last_checked_at: null,
  chapter_count: 10,
  chapters_done: 7,
  chapters_pending: 2,
  chapters_failed: 1,
  chapters_skipped: 0,
  disk_bytes: 2048,
  ...overrides,
});

export const job = (overrides: Record<string, unknown> = {}) => ({
  id: 5,
  type: "crawl",
  status: "running",
  novel_id: 1,
  total: 10,
  done: 4,
  failed: 0,
  skipped: 0,
  error: null,
  params: { url: "https://truyenhoan.com/kiem-khach-vo-danh.31415/" },
  created_at: "2026-10-14T12:00:00Z",
  started_at: "2026-10-14T12:00:01Z",
  finished_at: null,
  processed: 4,
  percent: 40.0,
  ...overrides,
});
