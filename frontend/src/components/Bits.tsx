import type { ChapterStatus, JobStatus, NovelStatus } from "../api/types";

/** Coloured label for a job, novel or chapter state. */
export function Badge({
  children,
  tone = "neutral",
  title,
}: {
  children: React.ReactNode;
  tone?: "neutral" | "ok" | "warn" | "err" | "accent";
  title?: string;
}) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

const JOB_LABELS: Record<JobStatus, { text: string; tone: "neutral" | "ok" | "warn" | "err" | "accent" }> = {
  queued: { text: "Đang chờ", tone: "neutral" },
  running: { text: "Đang chạy", tone: "accent" },
  paused: { text: "Tạm dừng", tone: "warn" },
  done: { text: "Xong", tone: "ok" },
  failed: { text: "Lỗi", tone: "err" },
  cancelled: { text: "Đã huỷ", tone: "neutral" },
};

export function JobBadge({ status }: { status: JobStatus }) {
  const label = JOB_LABELS[status];
  return <Badge tone={label.tone}>{label.text}</Badge>;
}

const NOVEL_LABELS: Record<NovelStatus, string> = {
  unknown: "Chưa rõ",
  ongoing: "Đang ra",
  completed: "Hoàn thành",
};

export function NovelStatusBadge({ status }: { status: NovelStatus }) {
  return (
    <Badge tone={status === "completed" ? "ok" : "neutral"}>{NOVEL_LABELS[status]}</Badge>
  );
}

/** "N chương mới" marker. Renders nothing at zero so callers can stay dumb. */
export function NewChaptersBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <Badge tone="accent" title="Số chương tìm thấy từ lần bạn xem gần nhất">
      +{count} chương mới
    </Badge>
  );
}

const CHAPTER_LABELS: Record<ChapterStatus, { text: string; tone: "neutral" | "ok" | "warn" | "err" }> = {
  pending: { text: "Chưa tải", tone: "neutral" },
  done: { text: "Đã tải", tone: "ok" },
  failed: { text: "Lỗi", tone: "err" },
  skipped_vip: { text: "VIP", tone: "warn" },
};

export function ChapterStatusBadge({ status }: { status: ChapterStatus }) {
  const label = CHAPTER_LABELS[status];
  return <Badge tone={label.tone}>{label.text}</Badge>;
}

export function ProgressBar({
  percent,
  label,
}: {
  percent: number;
  label?: string;
}) {
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <div className="progress" role="progressbar" aria-valuenow={clamped} aria-valuemin={0} aria-valuemax={100}>
      <div className="progress-fill" style={{ width: `${clamped}%` }} />
      <span className="progress-label">{label ?? `${clamped.toFixed(1)}%`}</span>
    </div>
  );
}

export function Spinner({ label = "Đang tải…" }: { label?: string }) {
  return <p className="muted">{label}</p>;
}

export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="box box-error" role="alert">
      {message}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="box muted">{children}</div>;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
