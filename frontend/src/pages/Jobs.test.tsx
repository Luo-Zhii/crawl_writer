import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import Jobs from "./Jobs";
import { StubEventSource } from "../test/setup";
import { job, paged, renderPage, stubFetch } from "../test/utils";

function latestStream(): StubEventSource {
  const stream = StubEventSource.instances.at(-1);
  if (!stream) throw new Error("no EventSource was opened");
  return stream;
}

/** Deliver an SSE frame the way the server would, inside React's act scope. */
async function emit(type: string, data: unknown) {
  await act(async () => {
    latestStream().emit(type, data);
  });
}

describe("Jobs", () => {
  it("lists jobs with their progress", async () => {
    stubFetch({ "/api/jobs": paged([job()]) });

    renderPage(<Jobs />);

    expect(await screen.findByText("#5")).toBeInTheDocument();
    expect(screen.getByText("Đang chạy")).toBeInTheDocument();
    expect(screen.getByText(/40.0% · 4\/10 chương/)).toBeInTheDocument();
  });

  it("says so when there is nothing to show", async () => {
    stubFetch({ "/api/jobs": paged([]) });

    renderPage(<Jobs />);

    expect(await screen.findByText("Chưa có tiến trình nào.")).toBeInTheDocument();
  });

  it("opens a stream for an active job", async () => {
    StubEventSource.instances.length = 0;
    stubFetch({ "/api/jobs": paged([job({ status: "running" })]) });

    renderPage(<Jobs />);
    await screen.findByText("#5");

    await waitFor(() => expect(StubEventSource.instances.length).toBeGreaterThan(0));
    expect(latestStream().url).toBe("/api/jobs/5/events");
  });

  it("does not open a stream for a finished job", async () => {
    StubEventSource.instances.length = 0;
    stubFetch({ "/api/jobs": paged([job({ status: "done", percent: 100 })]) });

    renderPage(<Jobs />);
    await screen.findByText("Xong");

    expect(StubEventSource.instances).toHaveLength(0);
  });

  it("updates the bar as progress frames arrive", async () => {
    StubEventSource.instances.length = 0;
    stubFetch({ "/api/jobs": paged([job()]) });

    renderPage(<Jobs />);
    await screen.findByText("#5");
    await waitFor(() => expect(StubEventSource.instances.length).toBeGreaterThan(0));

    await emit("progress", {
      job_id: 5,
      status: "running",
      total: 10,
      done: 9,
      failed: 1,
      skipped: 0,
      message: "chương 9",
      chapter: 9,
      processed: 10,
      percent: 100,
    });

    expect(await screen.findByText(/9\/10 chương/)).toBeInTheDocument();
    expect(screen.getByText("1 lỗi")).toBeInTheDocument();
  });

  it("shows the final state when the stream reports it", async () => {
    StubEventSource.instances.length = 0;
    stubFetch({ "/api/jobs": paged([job()]) });

    renderPage(<Jobs />);
    await screen.findByText("#5");
    await waitFor(() => expect(StubEventSource.instances.length).toBeGreaterThan(0));

    await emit("progress", {
      job_id: 5,
      status: "done",
      total: 10,
      done: 10,
      failed: 0,
      skipped: 0,
      message: null,
      chapter: 10,
      processed: 10,
      percent: 100,
    });

    expect(await screen.findByText("Xong")).toBeInTheDocument();
  });

  it("offers pause for a running job and calls the endpoint", async () => {
    const { calls } = stubFetch({
      "/api/jobs/5/pause": job({ status: "paused" }),
      "/api/jobs": paged([job({ status: "running" })]),
    });

    renderPage(<Jobs />);
    await userEvent.click(await screen.findByRole("button", { name: "Tạm dừng" }));

    await waitFor(() =>
      expect(calls.some((call) => call.url.includes("/pause") && call.method === "POST")).toBe(
        true,
      ),
    );
  });

  it("offers resume for a paused job", async () => {
    stubFetch({ "/api/jobs": paged([job({ status: "paused" })]) });

    renderPage(<Jobs />);

    expect(await screen.findByRole("button", { name: "Chạy tiếp" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tạm dừng" })).not.toBeInTheDocument();
  });

  it("hides controls for a job that already finished", async () => {
    stubFetch({ "/api/jobs": paged([job({ status: "cancelled" })]) });

    renderPage(<Jobs />);
    await screen.findByText("Đã huỷ");

    expect(screen.queryByRole("button", { name: "Huỷ" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tạm dừng" })).not.toBeInTheDocument();
  });

  it("surfaces the error message of a failed job", async () => {
    stubFetch({
      "/api/jobs": paged([job({ status: "failed", error: "blocked: forbidden" })]),
    });

    renderPage(<Jobs />);

    expect(await screen.findByText("blocked: forbidden")).toBeInTheDocument();
  });

  it("labels an update job by what it does, not by a url", async () => {
    stubFetch({ "/api/jobs": paged([job({ type: "update", params: {} })]) });

    renderPage(<Jobs />);

    expect(await screen.findByText("Cập nhật chương mới")).toBeInTheDocument();
  });
});
