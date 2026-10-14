import "@testing-library/jest-dom/vitest";

import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// jsdom has no EventSource, and the jobs page opens one for active jobs.
class StubEventSource {
  static instances: StubEventSource[] = [];

  onopen: (() => void) | null = null;
  readonly listeners = new Map<string, ((event: MessageEvent) => void)[]>();
  closed = false;

  constructor(readonly url: string) {
    StubEventSource.instances.push(this);
  }

  addEventListener(type: string, handler: (event: MessageEvent) => void) {
    const existing = this.listeners.get(type) ?? [];
    this.listeners.set(type, [...existing, handler]);
  }

  removeEventListener() {}

  close() {
    this.closed = true;
  }

  /** Test helper: deliver a frame as the server would. */
  emit(type: string, data: unknown) {
    for (const handler of this.listeners.get(type) ?? []) {
      handler(new MessageEvent(type, { data: JSON.stringify(data) }));
    }
  }
}

vi.stubGlobal("EventSource", StubEventSource);

export { StubEventSource };
