import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { listSources, previewUrl, startCrawl } from "../api/client";
import type { Preview } from "../api/types";
import { Badge, ErrorBox, NovelStatusBadge, Spinner } from "../components/Bits";

export default function AddNovel() {
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const sources = useQuery({ queryKey: ["sources"], queryFn: listSources });

  const lookup = useMutation({
    mutationFn: previewUrl,
    onSuccess: setPreview,
  });

  const crawl = useMutation({
    mutationFn: startCrawl,
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["novels"] });
      navigate(`/jobs?watch=${job.id}`);
    },
  });

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) return;
    setPreview(null);
    lookup.mutate(trimmed);
  };

  return (
    <section>
      <div className="page-head">
        <h1>Thêm truyện</h1>
      </div>

      <form onSubmit={submit} className="url-form">
        <input
          type="url"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="Dán link truyện hoặc link một chương"
          aria-label="Link truyện"
          required
        />
        <button type="submit" className="primary" disabled={lookup.isPending}>
          {lookup.isPending ? "Đang kiểm tra…" : "Kiểm tra"}
        </button>
      </form>

      <p className="muted small">
        Dán link trang truyện, hoặc link chương bạn đang đọc cũng được — hệ thống
        sẽ tự tìm về trang truyện.
      </p>

      {lookup.error && <ErrorBox error={lookup.error} />}

      {preview && (
        <PreviewCard
          preview={preview}
          onCrawl={() => crawl.mutate(preview.url)}
          busy={crawl.isPending}
        />
      )}

      {crawl.error && <ErrorBox error={crawl.error} />}

      <h2 className="section-title">Site đang hỗ trợ</h2>
      {sources.isLoading && <Spinner />}
      {sources.error && <ErrorBox error={sources.error} />}
      {sources.data && (
        <ul className="source-list">
          {sources.data.map((source) => (
            <li key={source.key}>
              <strong>{source.name}</strong>
              <span className="muted"> · {source.domains.join(", ")}</span>
              <Badge tone={source.lang === "vi" ? "neutral" : "accent"}>
                {source.lang === "vi" ? "Việt" : "Trung"}
              </Badge>
              {source.needs_browser && (
                <Badge tone="warn" title="Site này chặn bot, cần trình duyệt nền">
                  cần browser
                </Badge>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function PreviewCard({
  preview,
  onCrawl,
  busy,
}: {
  preview: Preview;
  onCrawl: () => void;
  busy: boolean;
}) {
  return (
    <article className="box preview">
      <div className="preview-cover">
        {preview.cover_url ? (
          <img src={preview.cover_url} alt="" />
        ) : (
          <span className="cover-fallback">{preview.title.slice(0, 1)}</span>
        )}
      </div>

      <div className="preview-body">
        <h2>{preview.title}</h2>
        <p className="muted">{preview.author ?? "Chưa rõ tác giả"}</p>
        <p className="novel-meta">
          <NovelStatusBadge status={preview.status} />
          <span className="muted">{preview.source_name}</span>
          {preview.genres.map((genre) => (
            <Badge key={genre}>{genre}</Badge>
          ))}
        </p>
        {preview.description && <p className="preview-desc">{preview.description}</p>}

        {preview.novel_id !== null ? (
          <p className="box box-warn">
            Truyện này đã có trong thư viện.{" "}
            <Link to={`/novels/${preview.novel_id}`}>Mở trang truyện</Link> hoặc bấm
            tải để lấy các chương còn thiếu.
          </p>
        ) : null}

        <button type="button" className="primary" onClick={onCrawl} disabled={busy}>
          {busy ? "Đang tạo tiến trình…" : "Bắt đầu tải"}
        </button>
      </div>
    </article>
  );
}
