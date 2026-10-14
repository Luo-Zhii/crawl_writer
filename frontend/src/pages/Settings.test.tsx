import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import Settings from "./Settings";
import { renderPage, stubFetch } from "../test/utils";

const SETTINGS = {
  proxy: null,
  browser_enabled: true,
  per_domain_delay: 0.6,
  per_domain_concurrency: 4,
  request_timeout: 30,
  chapter_retry_limit: 3,
  cookies: {},
  api_keys: { gemini: null, openai: null, anthropic: null },
};

function parseBody(init?: RequestInit) {
  return JSON.parse(String(init?.body ?? "{}"));
}

describe("Settings", () => {
  it("shows the current limits", async () => {
    stubFetch({ "/api/settings": SETTINGS });

    renderPage(<Settings />);

    expect(await screen.findByLabelText(/Giãn cách mỗi request/)).toHaveValue(0.6);
    expect(screen.getByLabelText(/Số request song song/)).toHaveValue(4);
  });

  it("saves the limits form", async () => {
    const bodies: unknown[] = [];
    stubFetch({
      "/api/settings": (_url: string, init?: RequestInit) => {
        if (init?.method === "PUT") bodies.push(parseBody(init));
        return SETTINGS;
      },
    });

    renderPage(<Settings />);
    const delay = await screen.findByLabelText(/Giãn cách mỗi request/);
    await userEvent.clear(delay);
    await userEvent.type(delay, "1.5");
    await userEvent.click(screen.getByRole("button", { name: "Lưu cài đặt" }));

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ per_domain_delay: 1.5 });
  });

  it("sends an empty proxy as a cleared value", async () => {
    const bodies: Record<string, unknown>[] = [];
    stubFetch({
      "/api/settings": (_url: string, init?: RequestInit) => {
        if (init?.method === "PUT") bodies.push(parseBody(init));
        return SETTINGS;
      },
    });

    renderPage(<Settings />);
    await screen.findByLabelText(/^Proxy/);
    await userEvent.click(screen.getByRole("button", { name: "Lưu cài đặt" }));

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].proxy).toBe("");
  });

  it("toggles the browser setting immediately", async () => {
    const bodies: Record<string, unknown>[] = [];
    stubFetch({
      // The GET must keep reporting the original state, otherwise the
      // checkbox renders already-off and clicking it turns it back on.
      "/api/settings": (_url: string, init?: RequestInit) => {
        if (init?.method === "PUT") {
          bodies.push(parseBody(init));
          return { ...SETTINGS, browser_enabled: false };
        }
        return SETTINGS;
      },
    });

    renderPage(<Settings />);
    await userEvent.click(
      await screen.findByLabelText(/Cho phép dùng trình duyệt nền/),
    );

    await waitFor(() => expect(bodies[0]).toEqual({ browser_enabled: false }));
  });

  it("reports when Chromium is missing, with the fix", async () => {
    stubFetch({
      "/api/settings/browser-check": {
        available: false,
        detail: "Playwright is not installed. Install it with: ...",
      },
      "/api/settings": SETTINGS,
    });

    renderPage(<Settings />);
    await userEvent.click(await screen.findByRole("button", { name: "Kiểm tra Chromium" }));

    expect(await screen.findByText(/Playwright is not installed/)).toBeInTheDocument();
  });

  it("lists saved cookies with a count", async () => {
    stubFetch({
      "/api/settings": { ...SETTINGS, cookies: { "metruyencv.com": "sid=a; remember=b" } },
    });

    renderPage(<Settings />);

    expect(await screen.findByText("metruyencv.com")).toBeInTheDocument();
    expect(screen.getByText("2 cookie")).toBeInTheDocument();
  });

  it("adds a cookie for a domain", async () => {
    const bodies: Record<string, unknown>[] = [];
    stubFetch({
      "/api/settings": (_url: string, init?: RequestInit) => {
        if (init?.method === "PUT") bodies.push(parseBody(init));
        return SETTINGS;
      },
    });

    renderPage(<Settings />);
    await userEvent.type(await screen.findByLabelText("Domain"), "a.test");
    await userEvent.type(screen.getByLabelText("Cookie"), "sid=1");
    await userEvent.click(screen.getByRole("button", { name: "Thêm" }));

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].cookies).toEqual({ "a.test": "sid=1" });
  });

  it("shows a masked hint for a stored api key, never the key", async () => {
    stubFetch({
      "/api/settings": {
        ...SETTINGS,
        api_keys: { gemini: "••••9876", openai: null, anthropic: null },
      },
    });

    renderPage(<Settings />);

    expect(await screen.findByText("••••9876")).toBeInTheDocument();
    expect(screen.getAllByText("chưa có")).toHaveLength(2);
  });

  it("saves a pasted api key", async () => {
    const bodies: Record<string, unknown>[] = [];
    stubFetch({
      "/api/settings": (_url: string, init?: RequestInit) => {
        if (init?.method === "PUT") bodies.push(parseBody(init));
        return SETTINGS;
      },
    });

    renderPage(<Settings />);
    await userEvent.type(await screen.findByLabelText("API key Gemini"), "new-key");
    // Three "Lưu" buttons exist (one per provider) plus the form one; pick the
    // one in the Gemini row.
    const geminiRow = screen.getByLabelText("API key Gemini").closest("li")!;
    await userEvent.click(
      [...geminiRow.querySelectorAll("button")].find((b) => b.textContent === "Lưu")!,
    );

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0].api_keys).toEqual({ gemini: "new-key" });
  });

  it("surfaces a save failure", async () => {
    stubFetch({
      "/api/settings": (_url: string, init?: RequestInit) => {
        if (init?.method === "PUT") {
          return new Response(JSON.stringify({ detail: "delay too small" }), {
            status: 422,
            headers: { "Content-Type": "application/json" },
          });
        }
        return SETTINGS;
      },
    });

    renderPage(<Settings />);
    await screen.findByLabelText(/^Proxy/);
    await userEvent.click(screen.getByRole("button", { name: "Lưu cài đặt" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("delay too small");
  });
});
