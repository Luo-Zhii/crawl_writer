import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import { cancelJob, listJobs, pauseJob, resumeJob } from "../api/client";
import type { Job } from "../api/types";
import { useJobEvents } from "../hooks/useJobEvents";
import {
  Empty,
  ErrorBox,
  JobBadge,
  ProgressBar,
  Spinner,
  formatDate,
} from "../components/Bits";

const ACTIVE = new Set(["queued", "running", "paused"]);

export default function Jobs() {
  const [params] = useSearchParams();
  const watchId = params.get("watch");
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["jobs"],
    queryFn: () => listJobs({ limit: 50 }),
    // A light poll keeps the list fresh; per-job detail comes over SSE.
    refetchInterval: 5000,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
    queryClient.invalidateQueries({ queryKey: ["novels"] });
  };

  const pause = useMutation({ mutationFn: pauseJob, onSuccess: invalidate });
  const resume = useMutation({ mutationFn: resumeJob, onSuccess: invalidate });
  const cancel = useMutation({ mutationFn: cancelJob, onSuccess: invalidate });

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBox error={error} />;

  const jobs = data?.items ?? [];

  return (
    <section>
      <div className="page-head">
        <h1>Tiến trình</h1>
        <span className="muted">{data?.total ?? 0} tiến trình</span>
      </div>

      {jobs.length === 0 ? (
        <Empty>Chưa có tiến trình nào.</Empty>
      ) : (
        <ul className="job-list">
          {jobs.map((job) => (
            <JobRow
              key={job.id}
              job={job}
              highlight={String(job.id) === watchId}
              onPause={() => pause.mutate(job.id)}
              onResume={() => resume.mutate(job.id)}
              onCancel={() => cancel.mutate(job.id)}
            />
          ))}
        </ul>
      )}

      {pause.error && <ErrorBox error={pause.error} />}
      {resume.error && <ErrorBox error={resume.error} />}
      {cancel.error && <ErrorBox error={cancel.error} />}
    </section>
  );
}

function JobRow({
  job,
  highlight,
  onPause,
  onResume,
  onCancel,
}: {
  job: Job;
  highlight: boolean;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
}) {
  const live = ACTIVE.has(job.status);
  // Only active jobs get a stream; finished ones would just reconnect for a
  // snapshot we already have in the list.
  const { progress, connected } = useJobEvents(job.id, live);

  const status = progress?.status ?? job.status;
  const percent = progress?.percent ?? job.percent;
  const done = progress?.done ?? job.done;
  const failed = progress?.failed ?? job.failed;
  const skipped = progress?.skipped ?? job.skipped;
  const total = progress?.total ?? job.total;
  const message = progress?.message ?? job.error;

  const label =
    job.type === "update" ? "Cập nhật chương mới" : (job.params.url as string) ?? "Crawl";

  return (
    <li className={`job-card${highlight ? " job-highlight" : ""}`}>
      <div className="job-head">
        <div>
          <strong>#{job.id}</strong> <JobBadge status={status} />
          {live && !connected && (
            <span className="muted small"> · mất kết nối, đang thử lại</span>
          )}
        </div>
        <span className="muted small">{formatDate(job.created_at)}</span>
      </div>

      <p className="job-target" title={label}>
        {label}
      </p>

      <ProgressBar
        percent={percent}
        label={`${percent.toFixed(1)}% · ${done}/${total || "?"} chương`}
      />

      <p className="muted small job-counts">
        {failed > 0 && <span className="err">{failed} lỗi</span>}
        {skipped > 0 && <span className="warn">{skipped} chương VIP bị bỏ qua</span>}
        {message && <span>{message}</span>}
      </p>

      <div className="job-actions">
        {status === "running" && (
          <button type="button" onClick={onPause}>
            Tạm dừng
          </button>
        )}
        {(status === "paused" || status === "failed") && (
          <button type="button" onClick={onResume}>
            Chạy tiếp
          </button>
        )}
        {ACTIVE.has(status) && (
          <button type="button" onClick={onCancel} className="danger">
            Huỷ
          </button>
        )}
      </div>
    </li>
  );
}
