import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Library from "./Library";
import { errorResponse, novel, paged, renderPage, stubFetch } from "../test/utils";

describe("Library", () => {
  it("lists the novels in the library", async () => {
    stubFetch({ "/api/novels": paged([novel(), novel({ id: 2, title: "Tiên Môn" })]) });

    renderPage(<Library />);

    expect(await screen.findByText("Kiếm Khách Vô Danh")).toBeInTheDocument();
    expect(screen.getByText("Tiên Môn")).toBeInTheDocument();
    expect(screen.getByText("2 truyện")).toBeInTheDocument();
  });

  it("explains what to do when the library is empty", async () => {
    stubFetch({ "/api/novels": paged([]) });

    renderPage(<Library />);

    expect(await screen.findByText(/Chưa có truyện nào/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Thêm truyện" })).toBeInTheDocument();
  });

  it("shows the backend error instead of an empty page", async () => {
    stubFetch({ "/api/novels": errorResponse(500, "Database is locked") });

    renderPage(<Library />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Database is locked");
  });

  it("falls back to an initial when a novel has no cover", async () => {
    stubFetch({ "/api/novels": paged([novel({ cover_url: null })]) });

    renderPage(<Library />);

    expect(await screen.findByText("K")).toBeInTheDocument();
  });

  it("asks for confirmation before deleting, and does nothing if refused", async () => {
    const { calls } = stubFetch({ "/api/novels": paged([novel()]) });
    vi.spyOn(window, "confirm").mockReturnValue(false);

    renderPage(<Library />);
    await screen.findByText("Kiếm Khách Vô Danh");
    await userEvent.click(screen.getByRole("button", { name: "Xoá" }));

    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
  });

  it("deletes once confirmed", async () => {
    const { calls } = stubFetch({
      "/api/novels/1": new Response(null, { status: 204 }),
      "/api/novels": paged([novel()]),
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderPage(<Library />);
    await screen.findByText("Kiếm Khách Vô Danh");
    await userEvent.click(screen.getByRole("button", { name: "Xoá" }));

    await waitFor(() => {
      expect(calls.some((call) => call.method === "DELETE" && call.url.includes("/api/novels/1"))).toBe(
        true,
      );
    });
  });

  it("starts an update job without asking", async () => {
    const { calls } = stubFetch({
      "/api/novels/1/update": { id: 9 },
      "/api/novels": paged([novel()]),
    });

    renderPage(<Library />);
    await screen.findByText("Kiếm Khách Vô Danh");
    await userEvent.click(screen.getByRole("button", { name: "Tải chương mới" }));

    await waitFor(() => {
      expect(
        calls.some((call) => call.method === "POST" && call.url.includes("/update")),
      ).toBe(true);
    });
  });
});

describe("Library new-chapter badge", () => {
  it("marks a novel that gained chapters", async () => {
    stubFetch({ "/api/novels": paged([novel({ new_chapters: 4 })]) });

    renderPage(<Library />);

    expect(await screen.findByText("+4 chương mới")).toBeInTheDocument();
  });

  it("shows no badge when nothing is new", async () => {
    stubFetch({ "/api/novels": paged([novel({ new_chapters: 0 })]) });

    renderPage(<Library />);
    await screen.findByText("Kiếm Khách Vô Danh");

    // Narrow regex: the "Tải chương mới" button also contains "chương mới".
    expect(screen.queryByText(/^\+\d+ chương mới$/)).not.toBeInTheDocument();
  });

  it("badges only the novels that changed", async () => {
    stubFetch({
      "/api/novels": paged([
        novel({ id: 1, title: "Có mới", new_chapters: 2 }),
        novel({ id: 2, title: "Không mới", new_chapters: 0 }),
      ]),
    });

    renderPage(<Library />);
    await screen.findByText("Có mới");

    expect(screen.getAllByText(/^\+\d+ chương mới$/)).toHaveLength(1);
  });
});
