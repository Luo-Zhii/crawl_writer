import { useQuery } from "@tanstack/react-query";

import { getHealth } from "./api/client";

export default function App() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
  });

  return (
    <main style={{ maxWidth: 720, margin: "4rem auto", padding: "0 1rem" }}>
      <h1>crawl_writer</h1>
      <p style={{ color: "var(--text-soft)" }}>
        Tool crawl truyện chữ về máy để đọc offline.
      </p>

      {isLoading && <p>Đang kiểm tra backend…</p>}
      {error && (
        <p style={{ color: "var(--err)" }}>
          Không gọi được backend. Chạy <code>make dev-api</code> rồi thử lại.
        </p>
      )}
      {data && (
        <p style={{ color: "var(--ok)" }}>
          API OK — version {data.version}
        </p>
      )}
    </main>
  );
}
