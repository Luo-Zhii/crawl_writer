import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Route, Routes } from "react-router-dom";

import Reader from "./Reader";
import { errorResponse, paged, renderPage, stubFetch } from "../test/utils";

const CHAPTER = {
  number: 2,
  title: "Chương 2: Người gác cổng",
  text: "Đoạn một.\n\nĐoạn hai.",
  translated: false,
  has_translation: false,
  prev_number: 1,
  next_number: 3,
  novel_id: 7,
  novel_title: "Kiếm Khách Vô Danh",
};

/** Reader reads :id and :number from the route, so it needs a real route. */
function renderReader(route = "/novels/7/doc/2") {
  return renderPage(
    <Routes>
      <Route path="/novels/:id/doc/:number" element={<Reader />} />
    </Routes>,
    { route },
  );
}

describe("Reader", () => {
  it("shows the chapter as paragraphs", async () => {
    stubFetch({ "/api/novels/7/chapters/2": CHAPTER, "/api/novels/7/progress": {} });

    renderReader();

    expect(await screen.findByText("Chương 2: Người gác cổng")).toBeInTheDocument();
    expect(screen.getByText("Đoạn một.")).toBeInTheDocument();
    expect(screen.getByText("Đoạn hai.")).toBeInTheDocument();
  });

  it("links back to the novel", async () => {
    stubFetch({ "/api/novels/7/chapters/2": CHAPTER, "/api/novels/7/progress": {} });

    renderReader();

    const back = await screen.findByRole("link", { name: /Kiếm Khách Vô Danh/ });
    expect(back).toHaveAttribute("href", "/novels/7");
  });

  it("saves the reading position on open", async () => {
    const { calls } = stubFetch({
      "/api/novels/7/chapters/2": CHAPTER,
      "/api/novels/7/progress": {},
    });

    renderReader();
    await screen.findByText("Chương 2: Người gác cổng");

    await waitFor(() =>
      expect(
        calls.some((c) => c.method === "PUT" && c.url.includes("/progress")),
      ).toBe(true),
    );
  });

  it("offers both neighbours when they exist", async () => {
    stubFetch({ "/api/novels/7/chapters/2": CHAPTER, "/api/novels/7/progress": {} });

    renderReader();

    expect(await screen.findByRole("button", { name: /Chương trước/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Chương sau/ })).toBeEnabled();
  });

  it("disables navigation at the ends of the book", async () => {
    stubFetch({
      "/api/novels/7/chapters/2": { ...CHAPTER, prev_number: null, next_number: null },
      "/api/novels/7/progress": {},
    });

    renderReader();

    expect(await screen.findByRole("button", { name: /Chương trước/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Chương sau/ })).toBeDisabled();
  });

  it("hides the translation toggle when there is no translation", async () => {
    stubFetch({ "/api/novels/7/chapters/2": CHAPTER, "/api/novels/7/progress": {} });

    renderReader();
    await screen.findByText("Chương 2: Người gác cổng");

    expect(screen.queryByRole("button", { name: /bản dịch/i })).not.toBeInTheDocument();
  });

  it("offers the toggle and marks translated text", async () => {
    stubFetch({
      "/api/novels/7/chapters/2": {
        ...CHAPTER,
        translated: true,
        has_translation: true,
      },
      "/api/novels/7/progress": {},
    });

    renderReader();

    expect(await screen.findByText("bản dịch")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Xem nguyên văn" }),
    ).toBeInTheDocument();
  });

  it("lets the reader change font size", async () => {
    stubFetch({ "/api/novels/7/chapters/2": CHAPTER, "/api/novels/7/progress": {} });

    renderReader();
    const slider = await screen.findByLabelText(/Cỡ chữ/);

    expect(slider).toHaveValue("18");
  });

  it("opens the table of contents on demand", async () => {
    stubFetch({
      "/api/novels/7/chapters/2": CHAPTER,
      "/api/novels/7/chapters": paged([
        {
          id: 1,
          number: 1,
          title: "Chương 1",
          volume: null,
          status: "done",
          char_count: 10,
          has_translation: false,
          fetched_at: null,
        },
      ]),
      "/api/novels/7/progress": {},
    });

    renderReader();
    await userEvent.click(await screen.findByRole("button", { name: "Mục lục" }));

    expect(await screen.findByRole("link", { name: "Chương 1" })).toHaveAttribute(
      "href",
      "/novels/7/doc/1",
    );
  });

  it("explains a chapter that was never downloaded", async () => {
    stubFetch({
      "/api/novels/7/chapters/2": errorResponse(
        409,
        "This chapter has not been downloaded yet",
      ),
      "/api/novels/7/progress": {},
    });

    renderReader();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "has not been downloaded",
    );
  });
});
