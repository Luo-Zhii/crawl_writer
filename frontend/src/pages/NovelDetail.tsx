import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  deleteNovel,
  exportUrl,
  getNovel,
  listChapters,
  startTranslation,
  startUpdate,
  updateNovel,
} from "../api/client";
import GlossaryPanel from "../components/GlossaryPanel";
import type { ChapterStatus, ExportFormat } from "../api/types";
import {
  Badge,
  ChapterStatusBadge,
  Empty,
  ErrorBox,
  NovelStatusBadge,
  ProgressBar,
  Spinner,
  formatBytes,
  formatDate,
} from "../components/Bits";

const PAGE_SIZE = 100;

export default function NovelDetail() {
  const { id } = useParams();
  const novelId = Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [filter, setFilter] = useState<ChapterStatus | "">("");
  const [page, setPage] = useState(0);

  const novel = useQuery({
    queryKey: ["novel", novelId],
    queryFn: () => getNovel(novelId),
    enabled: Number.isFinite(novelId),
  });

  const chapters = useQuery({
    queryKey: ["chapters", novelId, filter, page],
    queryFn: () =>
      listChapters(novelId, {
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        status: filter || undefined,
      }),
    enabled: Number.isFinite(novelId),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["novel", novelId] });
    queryClient.invalidateQueries({ queryKey: ["novels"] });
  };

  const follow = useMutation({
    mutationFn: (followed: boolean) => updateNovel(novelId, { followed }),
    onSuccess: invalidate,
  });

  const update = useMutation({
    mutationFn: () => startUpdate(novelId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });

  const translate = useMutation({
    mutationFn: (force: boolean) => startTranslation(novelId, force),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });

  const remove = useMutation({
    mutationFn: () => deleteNovel(novelId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["novels"] });
      navigate("/");
    },
  });

  if (novel.isLoading) return <Spinner />;
  if (novel.error) return <ErrorBox error={novel.error} />;
  if (!novel.data) return <Empty>Không tìm thấy truyện.</Empty>;

  const data = novel.data;
  const percent = data.chapter_count
    ? ((data.chapters_done + data.chapters_skipped) / data.chapter_count) * 100
    : 0;
  const pages = Math.ceil((chapters.data?.total ?? 0) / PAGE_SIZE);

  return (
    <section>
      <p className="muted small">
        <Link to="/">← Thư viện</Link>
      </p>

      <article className="novel-detail">
        <div className="detail-cover">
          {data.cover_url ? (
            <img src={data.cover_url} alt="" />
          ) : (
            <span className="cover-fallback">{data.title.slice(0, 1)}</span>
          )}
        </div>

        <div>
          <h1>{data.title}</h1>
          <p className="muted">{data.author ?? "Chưa rõ tác giả"}</p>

          <p className="novel-meta">
            <NovelStatusBadge status={data.status} />
            {data.genres.map((genre) => (
              <Badge key={genre}>{genre}</Badge>
            ))}
          </p>

          <p className="muted small">
            Nguồn:{" "}
            <a href={data.source_url} target="_blank" rel="noreferrer">
              {data.source}
            </a>
            {" · "}
            {formatBytes(data.disk_bytes)} trên đĩa
            {data.last_checked_at && ` · kiểm tra lần cuối ${formatDate(data.last_checked_at)}`}
          </p>

          <ProgressBar
            percent={percent}
            label={`${data.chapters_done}/${data.chapter_count} chương đã tải`}
          />

          <p className="muted small">
            {data.chapters_pending > 0 && `${data.chapters_pending} chưa tải · `}
            {data.chapters_failed > 0 && `${data.chapters_failed} lỗi · `}
            {data.chapters_skipped > 0 && `${data.chapters_skipped} VIP bị bỏ qua`}
          </p>

          {data.description && <p className="preview-desc">{data.description}</p>}

          <div className="detail-actions">
            <button type="button" onClick={() => update.mutate()} disabled={update.isPending}>
              Tải chương mới
            </button>
            <button
              type="button"
              onClick={() => follow.mutate(!data.followed)}
              disabled={follow.isPending}
            >
              {data.followed ? "Bỏ theo dõi" : "Theo dõi"}
            </button>
            <button
              type="button"
              className="danger"
              onClick={() => {
                if (window.confirm(`Xoá "${data.title}" và toàn bộ chương đã tải?`)) {
                  remove.mutate();
                }
              }}
              disabled={remove.isPending}
            >
              Xoá
            </button>
          </div>

          {data.lang === "zh" && (
            <div className="detail-actions">
              <button
                type="button"
                className="primary"
                onClick={() => translate.mutate(false)}
                disabled={translate.isPending}
              >
                Dịch sang tiếng Việt
              </button>
              <button
                type="button"
                onClick={() => translate.mutate(true)}
                disabled={translate.isPending}
                title="Dịch lại cả những chương đã có bản dịch"
              >
                Dịch lại toàn bộ
              </button>
            </div>
          )}

          <div className="detail-actions">
            {(["epub", "txt", "json"] as ExportFormat[]).map((format) => (
              <a
                key={format}
                className="button-link"
                href={exportUrl(novelId, format)}
                // Plain link so the browser handles the download itself.
                download
              >
                Tải {format.toUpperCase()}
              </a>
            ))}
            <a
              className="button-link"
              href={exportUrl(novelId, "epub", { volumeSize: 500 })}
              download
            >
              EPUB chia phần
            </a>
            {data.lang === "zh" && (
              <a
                className="button-link"
                href={exportUrl(novelId, "epub", { translated: true })}
                download
                title="Chương nào chưa dịch sẽ lấy bản gốc"
              >
                EPUB bản dịch
              </a>
            )}
          </div>

          {(update.isSuccess || translate.isSuccess) && (
            <p className="muted small">
              Đã tạo tiến trình. Xem ở <Link to="/jobs">Tiến trình</Link>.
            </p>
          )}
          {update.error && <ErrorBox error={update.error} />}
          {translate.error && <ErrorBox error={translate.error} />}
          {remove.error && <ErrorBox error={remove.error} />}
        </div>
      </article>

      {data.lang === "zh" && (
        <>
          <h2 className="section-title">Glossary tên riêng</h2>
          <GlossaryPanel novelId={novelId} />
        </>
      )}

      <h2 className="section-title">Danh sách chương</h2>

      <div className="filter-row">
        <label>
          Lọc:{" "}
          <select
            value={filter}
            onChange={(event) => {
              setFilter(event.target.value as ChapterStatus | "");
              setPage(0);
            }}
          >
            <option value="">Tất cả</option>
            <option value="done">Đã tải</option>
            <option value="pending">Chưa tải</option>
            <option value="failed">Lỗi</option>
            <option value="skipped_vip">VIP</option>
          </select>
        </label>
        {pages > 1 && (
          <span className="pager">
            <button type="button" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>
              ←
            </button>
            <span className="muted small">
              Trang {page + 1}/{pages}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
              disabled={page >= pages - 1}
            >
              →
            </button>
          </span>
        )}
      </div>

      {chapters.isLoading && <Spinner />}
      {chapters.error && <ErrorBox error={chapters.error} />}
      {chapters.data && chapters.data.items.length === 0 && (
        <Empty>Không có chương nào khớp bộ lọc.</Empty>
      )}
      {chapters.data && chapters.data.items.length > 0 && (
        <table className="chapter-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Tên chương</th>
              <th>Trạng thái</th>
              <th>Độ dài</th>
            </tr>
          </thead>
          <tbody>
            {chapters.data.items.map((chapter) => (
              <tr key={chapter.id}>
                <td className="num">{chapter.number}</td>
                <td>{chapter.title}</td>
                <td>
                  <ChapterStatusBadge status={chapter.status} />
                </td>
                <td className="num muted">
                  {chapter.char_count ? `${chapter.char_count.toLocaleString("vi-VN")} ký tự` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
