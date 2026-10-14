import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { deleteNovel, listNovels, startUpdate } from "../api/client";
import type { NovelSummary } from "../api/types";
import {
  Empty,
  ErrorBox,
  NewChaptersBadge,
  NovelStatusBadge,
  Spinner,
  formatDate,
} from "../components/Bits";

export default function Library() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["novels"],
    queryFn: () => listNovels({ limit: 100 }),
  });

  const remove = useMutation({
    mutationFn: deleteNovel,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["novels"] }),
  });

  const update = useMutation({
    mutationFn: startUpdate,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBox error={error} />;

  const novels = data?.items ?? [];

  return (
    <section>
      <div className="page-head">
        <h1>Thư viện</h1>
        <span className="muted">{data?.total ?? 0} truyện</span>
      </div>

      {novels.length === 0 ? (
        <Empty>
          Chưa có truyện nào. <Link to="/add">Thêm truyện</Link> bằng cách dán link.
        </Empty>
      ) : (
        <ul className="novel-grid">
          {novels.map((novel) => (
            <NovelRow
              key={novel.id}
              novel={novel}
              onDelete={() => {
                if (
                  window.confirm(
                    `Xoá "${novel.title}" khỏi thư viện? Toàn bộ chương đã tải sẽ bị xoá khỏi đĩa.`,
                  )
                ) {
                  remove.mutate(novel.id);
                }
              }}
              onUpdate={() => update.mutate(novel.id)}
              busy={remove.isPending || update.isPending}
            />
          ))}
        </ul>
      )}

      {remove.error && <ErrorBox error={remove.error} />}
      {update.error && <ErrorBox error={update.error} />}
      {update.isSuccess && (
        <p className="muted">
          Đã tạo tiến trình cập nhật. Xem ở <Link to="/jobs">Tiến trình</Link>.
        </p>
      )}
    </section>
  );
}

function NovelRow({
  novel,
  onDelete,
  onUpdate,
  busy,
}: {
  novel: NovelSummary;
  onDelete: () => void;
  onUpdate: () => void;
  busy: boolean;
}) {
  return (
    <li className="novel-card">
      <Link to={`/novels/${novel.id}`} className="novel-cover">
        {novel.cover_url ? (
          // Covers come from the source site; a broken one must not break layout.
          <img src={novel.cover_url} alt="" loading="lazy" />
        ) : (
          <span className="cover-fallback">{novel.title.slice(0, 1)}</span>
        )}
      </Link>

      <div className="novel-body">
        <h2>
          <Link to={`/novels/${novel.id}`}>{novel.title}</Link>
        </h2>
        <p className="muted">{novel.author ?? "Chưa rõ tác giả"}</p>
        <p className="novel-meta">
          <NovelStatusBadge status={novel.status} />
          <NewChaptersBadge count={novel.new_chapters} />
          <span className="muted">{novel.source}</span>
          {novel.lang === "zh" && <span className="muted">· raw Trung</span>}
        </p>
        <p className="muted small">Cập nhật {formatDate(novel.updated_at)}</p>
      </div>

      <div className="novel-actions">
        <Link
          className="button-link"
          to={`/novels/${novel.id}/doc/${novel.last_read_chapter ?? 1}`}
        >
          {novel.last_read_chapter ? "Đọc tiếp" : "Đọc"}
        </Link>
        <button type="button" onClick={onUpdate} disabled={busy}>
          Tải chương mới
        </button>
        <button type="button" onClick={onDelete} disabled={busy} className="danger">
          Xoá
        </button>
      </div>
    </li>
  );
}
