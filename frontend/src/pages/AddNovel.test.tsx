import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import AddNovel from "./AddNovel";
import { errorResponse, renderPage, stubFetch } from "../test/utils";

const PREVIEW = {
  source: "truyenhoan",
  source_name: "Truyện Hoàn",
  url: "https://truyenhoan.com/kiem-khach-vo-danh.31415/",
  title: "Kiếm Khách Vô Danh",
  author: "Mộng Trung Nhân",
  cover_url: null,
  description: "Một kiếm khách không tên.",
  genres: ["Tiên Hiệp", "Kiếm Hiệp"],
  status: "ongoing",
  lang: "vi",
  novel_id: null,
};

const SOURCES = [
  {
    key: "truyenhoan",
    name: "Truyện Hoàn",
    domains: ["truyenhoan.com"],
    lang: "vi",
    needs_browser: false,
  },
  {
    key: "metruyencv",
    name: "MeTruyenCV",
    domains: ["metruyencv.com"],
    lang: "vi",
    needs_browser: true,
  },
];

describe("AddNovel", () => {
  it("lists the supported sites and flags the ones needing a browser", async () => {
    stubFetch({ "/api/sources": SOURCES });

    renderPage(<AddNovel />);

    expect(await screen.findByText("Truyện Hoàn")).toBeInTheDocument();
    expect(screen.getByText("cần browser")).toBeInTheDocument();
  });

  it("previews a pasted url before anything is downloaded", async () => {
    const { calls } = stubFetch({ "/api/preview": PREVIEW, "/api/sources": [] });

    renderPage(<AddNovel />);
    await userEvent.type(
      screen.getByLabelText("Link truyện"),
      "https://truyenhoan.com/kiem-khach-vo-danh.31415/",
    );
    await userEvent.click(screen.getByRole("button", { name: "Kiểm tra" }));

    expect(await screen.findByText("Kiếm Khách Vô Danh")).toBeInTheDocument();
    expect(screen.getByText("Mộng Trung Nhân")).toBeInTheDocument();
    expect(screen.getByText("Tiên Hiệp")).toBeInTheDocument();
    // Preview must not start a crawl on its own.
    expect(calls.some((call) => call.url.includes("/api/jobs"))).toBe(false);
  });

  it("starts the crawl only when asked", async () => {
    const { calls } = stubFetch({
      "/api/preview": PREVIEW,
      "/api/jobs": { id: 3 },
      "/api/sources": [],
    });

    renderPage(<AddNovel />);
    await userEvent.type(screen.getByLabelText("Link truyện"), "https://truyenhoan.com/a.1/");
    await userEvent.click(screen.getByRole("button", { name: "Kiểm tra" }));
    await userEvent.click(await screen.findByRole("button", { name: "Bắt đầu tải" }));

    await waitFor(() =>
      expect(
        calls.some((call) => call.url.includes("/api/jobs") && call.method === "POST"),
      ).toBe(true),
    );
  });

  it("warns when the novel is already in the library", async () => {
    stubFetch({
      "/api/preview": { ...PREVIEW, novel_id: 12 },
      "/api/sources": [],
    });

    renderPage(<AddNovel />);
    await userEvent.type(screen.getByLabelText("Link truyện"), "https://truyenhoan.com/a.1/");
    await userEvent.click(screen.getByRole("button", { name: "Kiểm tra" }));

    expect(await screen.findByText(/đã có trong thư viện/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Mở trang truyện" })).toHaveAttribute(
      "href",
      "/novels/12",
    );
  });

  it("shows why an unsupported url was rejected", async () => {
    stubFetch({
      "/api/preview": errorResponse(422, "No adapter handles this URL: https://example.com/x"),
      "/api/sources": [],
    });

    renderPage(<AddNovel />);
    await userEvent.type(screen.getByLabelText("Link truyện"), "https://example.com/x");
    await userEvent.click(screen.getByRole("button", { name: "Kiểm tra" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("No adapter handles this URL");
  });

  it("passes on the hint when a site blocks us", async () => {
    stubFetch({
      "/api/preview": errorResponse(
        502,
        "Site refused the request: forbidden. This source needs a browser, a proxy or cookies.",
      ),
      "/api/sources": [],
    });

    renderPage(<AddNovel />);
    await userEvent.type(screen.getByLabelText("Link truyện"), "https://truyenhoan.com/a.1/");
    await userEvent.click(screen.getByRole("button", { name: "Kiểm tra" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("needs a browser");
  });
});
