import { describe, expect, it } from "vitest";

import { ApiError, exportUrl, jobEventsUrl, listChapters, listNovels } from "./client";
import { errorResponse, paged, stubFetch } from "../test/utils";

describe("exportUrl", () => {
  it("builds a plain download link", () => {
    expect(exportUrl(7, "epub")).toBe("/api/novels/7/export?format=epub");
  });

  it("includes the options the backend expects", () => {
    const url = exportUrl(7, "epub", { translated: true, volumeSize: 500 });

    expect(url).toContain("format=epub");
    expect(url).toContain("translated=true");
    expect(url).toContain("volume_size=500");
  });

  it("omits options that are not set", () => {
    expect(exportUrl(7, "txt")).not.toContain("translated");
    expect(exportUrl(7, "txt")).not.toContain("volume_size");
  });
});

describe("jobEventsUrl", () => {
  it("points at the SSE endpoint", () => {
    expect(jobEventsUrl(3)).toBe("/api/jobs/3/events");
  });
});

describe("query building", () => {
  it("sends only the params it was given", async () => {
    const { calls } = stubFetch({ "/api/novels": paged([]) });

    await listNovels();
    expect(calls[0].url).toBe("/api/novels");

    await listNovels({ limit: 10, followed: true });
    expect(calls[1].url).toBe("/api/novels?limit=10&followed=true");
  });

  it("passes the chapter status filter through", async () => {
    const { calls } = stubFetch({ "/api/novels/1/chapters": paged([]) });

    await listChapters(1, { status: "failed", limit: 50 });

    expect(calls[0].url).toBe("/api/novels/1/chapters?limit=50&status=failed");
  });
});

describe("error handling", () => {
  it("surfaces the backend detail message", async () => {
    stubFetch({ "/api/novels": errorResponse(409, "No downloaded chapters") });

    await expect(listNovels()).rejects.toThrow("No downloaded chapters");
  });

  it("keeps the status code for the caller", async () => {
    stubFetch({ "/api/novels": errorResponse(404, "Novel not found") });

    await expect(listNovels()).rejects.toMatchObject({ status: 404 });
    expect(new ApiError("x", 500)).toBeInstanceOf(Error);
  });

  it("falls back to the status text when there is no JSON body", async () => {
    globalThis.fetch = (async () =>
      new Response("not json", { status: 500, statusText: "Server Error" })) as typeof fetch;

    await expect(listNovels()).rejects.toThrow("Server Error");
  });
});
