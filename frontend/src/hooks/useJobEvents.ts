import { useEffect, useRef, useState } from "react";

import { jobEventsUrl } from "../api/client";
import type { Job, ProgressEvent } from "../api/types";

export interface JobStream {
  /** Latest progress, or null until the first frame arrives. */
  progress: ProgressEvent | null;
  /** True once the server says the job reached a final state. */
  finished: boolean;
  connected: boolean;
}

const FINAL_STATUSES = new Set(["done", "failed", "cancelled"]);

/**
 * Subscribe to one job's server-sent events.
 *
 * The backend sends a snapshot first, so a tab opened halfway through a crawl
 * shows the real position immediately instead of starting from zero.
 */
export function useJobEvents(jobId: number | null, enabled = true): JobStream {
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [finished, setFinished] = useState(false);
  const [connected, setConnected] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (jobId === null || !enabled) return;

    setProgress(null);
    setFinished(false);

    const source = new EventSource(jobEventsUrl(jobId));
    sourceRef.current = source;

    const close = () => {
      source.close();
      setConnected(false);
    };

    source.onopen = () => setConnected(true);

    source.addEventListener("snapshot", (event) => {
      const job = JSON.parse((event as MessageEvent).data) as Job;
      setProgress({
        job_id: job.id,
        status: job.status,
        total: job.total,
        done: job.done,
        failed: job.failed,
        skipped: job.skipped,
        message: job.error,
        chapter: null,
        processed: job.processed,
        percent: job.percent,
      });
      if (FINAL_STATUSES.has(job.status)) setFinished(true);
    });

    source.addEventListener("progress", (event) => {
      const frame = JSON.parse((event as MessageEvent).data) as ProgressEvent;
      setProgress(frame);
      if (FINAL_STATUSES.has(frame.status)) setFinished(true);
    });

    source.addEventListener("end", () => {
      setFinished(true);
      close();
    });

    source.addEventListener("error", () => {
      // EventSource retries on its own; reflect the gap in the UI meanwhile.
      setConnected(false);
    });

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [jobId, enabled]);

  return { progress, finished, connected };
}
