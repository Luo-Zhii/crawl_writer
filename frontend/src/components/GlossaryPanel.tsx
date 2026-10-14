import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { addGlossaryTerm, deleteGlossaryTerm, listGlossary } from "../api/client";
import { ErrorBox, Spinner } from "./Bits";

/**
 * Per-novel term list.
 *
 * Machine translation renders the same character name several different ways
 * across a long novel, which is the main thing that makes a translated book
 * hard to follow. Pinning the names here fixes that.
 */
export default function GlossaryPanel({ novelId }: { novelId: number }) {
  const queryClient = useQueryClient();
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");

  const terms = useQuery({
    queryKey: ["glossary", novelId],
    queryFn: () => listGlossary(novelId),
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["glossary", novelId] });

  const add = useMutation({
    mutationFn: (term: { source: string; target: string }) =>
      addGlossaryTerm(novelId, term),
    onSuccess: () => {
      setSource("");
      setTarget("");
      invalidate();
    },
  });

  const remove = useMutation({
    mutationFn: (termId: number) => deleteGlossaryTerm(novelId, termId),
    onSuccess: invalidate,
  });

  return (
    <>
      <p className="muted small">
        Tên riêng hay bị dịch khác nhau ở mỗi chương. Thêm vào đây để cố định
        cách đọc. Ví dụ: 萧炎 → Tiêu Viêm.
      </p>

      {terms.isLoading && <Spinner />}
      {terms.error && <ErrorBox error={terms.error} />}

      {terms.data && terms.data.length > 0 && (
        <table className="chapter-table">
          <thead>
            <tr>
              <th>Nguyên văn</th>
              <th>Dịch thành</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {terms.data.map((term) => (
              <tr key={term.id}>
                <td>{term.source}</td>
                <td>{term.target}</td>
                <td>
                  <button
                    type="button"
                    onClick={() => remove.mutate(term.id)}
                    disabled={remove.isPending}
                  >
                    Xoá
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {terms.data && terms.data.length === 0 && (
        <p className="muted small">Chưa có từ nào.</p>
      )}

      <form
        className="url-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!source.trim() || !target.trim()) return;
          add.mutate({ source: source.trim(), target: target.trim() });
        }}
      >
        <input
          type="text"
          value={source}
          placeholder="萧炎"
          aria-label="Nguyên văn"
          onChange={(event) => setSource(event.target.value)}
        />
        <input
          type="text"
          value={target}
          placeholder="Tiêu Viêm"
          aria-label="Dịch thành"
          onChange={(event) => setTarget(event.target.value)}
        />
        <button type="submit" disabled={add.isPending}>
          Thêm từ
        </button>
      </form>

      {add.error && <ErrorBox error={add.error} />}
      {remove.error && <ErrorBox error={remove.error} />}

      <p className="muted small">
        Sửa glossary rồi dịch lại thì nhớ bấm "Dịch lại toàn bộ", vì những
        chương đã dịch được giữ nguyên.
      </p>
    </>
  );
}
