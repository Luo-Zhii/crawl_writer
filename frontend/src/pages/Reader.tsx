import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { listChapters, readChapter, saveProgress } from "../api/client";
import { Badge, ErrorBox, Spinner } from "../components/Bits";
import { FONT_RANGE, WIDTH_RANGE, useReaderPrefs } from "../hooks/useReaderPrefs";

export default function Reader() {
  const { id, number } = useParams();
  const novelId = Number(id);
  const chapterNumber = Number(number);
  const navigate = useNavigate();
  const { prefs, update } = useReaderPrefs();
  const [showToc, setShowToc] = useState(false);
  const topRef = useRef<HTMLDivElement>(null);

  const chapter = useQuery({
    queryKey: ["chapter", novelId, chapterNumber, prefs.translated],
    queryFn: () => readChapter(novelId, chapterNumber, prefs.translated),
    enabled: Number.isFinite(novelId) && Number.isFinite(chapterNumber),
  });

  const progress = useMutation({
    mutationFn: () => saveProgress(novelId, chapterNumber),
  });

  // Opening a chapter is what "I am reading here" means, so the position is
  // saved on load rather than asking the user to mark it.
  useEffect(() => {
    if (chapter.isSuccess) progress.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapter.isSuccess, novelId, chapterNumber]);

  // A new chapter should start at the top, not wherever the last one ended.
  useEffect(() => {
    topRef.current?.scrollIntoView({ block: "start" });
    setShowToc(false);
  }, [chapterNumber]);

  const data = chapter.data;
  const go = (target: number | null) => {
    if (target !== null) navigate(`/novels/${novelId}/doc/${target}`);
  };

  // Arrow keys are how people actually page through a long novel.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement) return;
      if (event.key === "ArrowLeft") go(data?.prev_number ?? null);
      if (event.key === "ArrowRight") go(data?.next_number ?? null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [data?.prev_number, data?.next_number, novelId]);

  if (chapter.isLoading) return <Spinner label="Đang mở chương…" />;
  if (chapter.error) return <ErrorBox error={chapter.error} />;
  if (!data) return null;

  const paragraphs = data.text.split("\n\n").filter((part) => part.trim());

  return (
    <article className="reader" ref={topRef}>
      <div className="reader-head">
        <Link to={`/novels/${novelId}`} className="small">
          ← {data.novel_title}
        </Link>

        <div className="reader-tools">
          <label className="small">
            Cỡ chữ
            <input
              type="range"
              min={FONT_RANGE.min}
              max={FONT_RANGE.max}
              step={FONT_RANGE.step}
              value={prefs.fontSize}
              onChange={(event) => update({ fontSize: Number(event.target.value) })}
            />
          </label>
          <label className="small">
            Bề rộng
            <input
              type="range"
              min={WIDTH_RANGE.min}
              max={WIDTH_RANGE.max}
              step={WIDTH_RANGE.step}
              value={prefs.width}
              onChange={(event) => update({ width: Number(event.target.value) })}
            />
          </label>
          {data.has_translation && (
            <button
              type="button"
              onClick={() => update({ translated: !prefs.translated })}
            >
              {data.translated ? "Xem nguyên văn" : "Xem bản dịch"}
            </button>
          )}
          <button type="button" onClick={() => setShowToc((open) => !open)}>
            Mục lục
          </button>
        </div>
      </div>

      {showToc && <TableOfContents novelId={novelId} current={chapterNumber} />}

      <h1 className="reader-title">{data.title}</h1>
      {data.translated && <Badge tone="accent">bản dịch</Badge>}

      <div
        className="reader-body"
        style={{
          fontSize: `${prefs.fontSize}px`,
          lineHeight: prefs.lineHeight,
          maxWidth: `${prefs.width}rem`,
        }}
      >
        {paragraphs.map((paragraph, index) => (
          // Chapter text has no stable per-paragraph id; the index is fine
          // because the list is replaced wholesale on navigation.
          <p key={index}>{paragraph}</p>
        ))}
      </div>

      <nav className="reader-nav">
        <button
          type="button"
          onClick={() => go(data.prev_number)}
          disabled={data.prev_number === null}
        >
          ← Chương trước
        </button>
        <span className="muted small">Chương {data.number}</span>
        <button
          type="button"
          className="primary"
          onClick={() => go(data.next_number)}
          disabled={data.next_number === null}
        >
          Chương sau →
        </button>
      </nav>

      <p className="muted small">Dùng mũi tên ← → để chuyển chương.</p>
    </article>
  );
}

function TableOfContents({
  novelId,
  current,
}: {
  novelId: number;
  current: number;
}) {
  const chapters = useQuery({
    queryKey: ["toc", novelId],
    queryFn: () => listChapters(novelId, { limit: 2000, status: "done" }),
  });

  if (chapters.isLoading) return <Spinner />;
  if (chapters.error) return <ErrorBox error={chapters.error} />;

  return (
    <div className="box toc">
      {chapters.data?.items.map((item) => (
        <Link
          key={item.id}
          to={`/novels/${novelId}/doc/${item.number}`}
          className={item.number === current ? "toc-current" : undefined}
        >
          {item.title}
        </Link>
      ))}
    </div>
  );
}
