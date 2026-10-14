import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { checkBrowser, deleteCookie, getSettings, saveSettings } from "../api/client";
import type { AppSettings, BrowserCheck, SettingsPatch } from "../api/types";
import { Badge, ErrorBox, Spinner } from "../components/Bits";

const PROVIDERS = [
  { key: "gemini", label: "Gemini" },
  { key: "openai", label: "OpenAI" },
  { key: "anthropic", label: "Anthropic" },
];

export default function Settings() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
  });

  const save = useMutation({
    mutationFn: saveSettings,
    onSuccess: (fresh) => queryClient.setQueryData(["settings"], fresh),
  });

  const removeCookie = useMutation({
    mutationFn: deleteCookie,
    onSuccess: (fresh) => queryClient.setQueryData(["settings"], fresh),
  });

  const [probe, setProbe] = useState<BrowserCheck | null>(null);
  const browserProbe = useMutation({ mutationFn: checkBrowser, onSuccess: setProbe });

  if (isLoading) return <Spinner />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;

  return (
    <section>
      <div className="page-head">
        <h1>Cài đặt</h1>
        {save.isSuccess && <span className="muted small">Đã lưu</span>}
      </div>

      {save.error && <ErrorBox error={save.error} />}

      <LimitsForm settings={data} onSave={(patch) => save.mutate(patch)} busy={save.isPending} />

      <h2 className="section-title">Trình duyệt nền</h2>
      <p className="muted small">
        Một số site chặn request thường và chỉ trả về trang kiểm tra JavaScript.
        Khi bật, những site đó sẽ được tải bằng Chromium ẩn. Chậm hơn nhiều nên
        chỉ dùng cho site thật sự cần.
      </p>

      <label className="check-row">
        <input
          type="checkbox"
          checked={data.browser_enabled}
          onChange={(event) => save.mutate({ browser_enabled: event.target.checked })}
        />
        Cho phép dùng trình duyệt nền khi bị chặn
      </label>

      <p>
        <button
          type="button"
          onClick={() => browserProbe.mutate()}
          disabled={browserProbe.isPending}
        >
          {browserProbe.isPending ? "Đang kiểm tra…" : "Kiểm tra Chromium"}
        </button>
      </p>

      {probe && (
        <div className={`box ${probe.available ? "" : "box-warn"}`}>
          {probe.available ? "Chromium hoạt động." : probe.detail}
        </div>
      )}

      <h2 className="section-title">Cookie theo site</h2>
      <p className="muted small">
        Dán cookie lấy từ trình duyệt của bạn (DevTools → Network → Request
        Headers → Cookie). Dùng cho site bắt đăng nhập, hoặc site mà Cloudflare
        chặn cả trình duyệt nền. Cookie thường hết hạn sau vài ngày.
      </p>

      <CookieEditor
        cookies={data.cookies}
        onAdd={(domain, value) =>
          save.mutate({ cookies: { ...data.cookies, [domain]: value } })
        }
        onRemove={(domain) => removeCookie.mutate(domain)}
        busy={save.isPending || removeCookie.isPending}
      />
      {removeCookie.error && <ErrorBox error={removeCookie.error} />}

      <h2 className="section-title">API key dịch</h2>
      <p className="muted small">
        Chỉ cần khi dùng engine dịch bằng LLM. Google Translate không cần key.
        Key được lưu ở máy bạn và không bao giờ được trả về qua API — chỉ hiện
        vài ký tự cuối để bạn phân biệt.
      </p>

      <ApiKeyEditor
        hints={data.api_keys}
        onSave={(provider, key) => save.mutate({ api_keys: { [provider]: key } })}
        busy={save.isPending}
      />
    </section>
  );
}

function LimitsForm({
  settings,
  onSave,
  busy,
}: {
  settings: AppSettings;
  onSave: (patch: SettingsPatch) => void;
  busy: boolean;
}) {
  const [form, setForm] = useState({
    proxy: settings.proxy ?? "",
    per_domain_delay: settings.per_domain_delay,
    per_domain_concurrency: settings.per_domain_concurrency,
    request_timeout: settings.request_timeout,
    chapter_retry_limit: settings.chapter_retry_limit,
  });

  // Keep the inputs in step when a save elsewhere refreshes the data.
  useEffect(() => {
    setForm({
      proxy: settings.proxy ?? "",
      per_domain_delay: settings.per_domain_delay,
      per_domain_concurrency: settings.per_domain_concurrency,
      request_timeout: settings.request_timeout,
      chapter_retry_limit: settings.chapter_retry_limit,
    });
  }, [settings]);

  return (
    <form
      className="settings-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSave({ ...form, proxy: form.proxy.trim() });
      }}
    >
      <label>
        Proxy
        <input
          type="text"
          value={form.proxy}
          placeholder="http://127.0.0.1:1080"
          aria-label="Proxy"
          onChange={(event) => setForm({ ...form, proxy: event.target.value })}
        />
        <span className="muted small">
          Cần cho site Trung bị chặn theo vùng. Để trống nếu không dùng.
        </span>
      </label>

      <label>
        Giãn cách mỗi request (giây)
        <input
          type="number"
          step="0.1"
          min="0"
          max="30"
          value={form.per_domain_delay}
          onChange={(event) =>
            setForm({ ...form, per_domain_delay: Number(event.target.value) })
          }
        />
        <span className="muted small">
          Hạ xuống thì nhanh hơn nhưng dễ bị site chặn. Mặc định 0.6.
        </span>
      </label>

      <label>
        Số request song song mỗi site
        <input
          type="number"
          min="1"
          max="16"
          value={form.per_domain_concurrency}
          onChange={(event) =>
            setForm({ ...form, per_domain_concurrency: Number(event.target.value) })
          }
        />
      </label>

      <label>
        Timeout mỗi request (giây)
        <input
          type="number"
          min="5"
          max="180"
          value={form.request_timeout}
          onChange={(event) =>
            setForm({ ...form, request_timeout: Number(event.target.value) })
          }
        />
      </label>

      <label>
        Số lần thử lại mỗi chương
        <input
          type="number"
          min="0"
          max="10"
          value={form.chapter_retry_limit}
          onChange={(event) =>
            setForm({ ...form, chapter_retry_limit: Number(event.target.value) })
          }
        />
      </label>

      <div>
        <button type="submit" className="primary" disabled={busy}>
          {busy ? "Đang lưu…" : "Lưu cài đặt"}
        </button>
      </div>
    </form>
  );
}

function CookieEditor({
  cookies,
  onAdd,
  onRemove,
  busy,
}: {
  cookies: Record<string, string>;
  onAdd: (domain: string, value: string) => void;
  onRemove: (domain: string) => void;
  busy: boolean;
}) {
  const [domain, setDomain] = useState("");
  const [value, setValue] = useState("");
  const entries = Object.entries(cookies);

  return (
    <>
      {entries.length > 0 && (
        <ul className="source-list">
          {entries.map(([host, raw]) => (
            <li key={host}>
              <strong>{host}</strong>
              <Badge>{raw.split(";").filter(Boolean).length} cookie</Badge>
              <button type="button" onClick={() => onRemove(host)} disabled={busy}>
                Xoá
              </button>
            </li>
          ))}
        </ul>
      )}

      <form
        className="url-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!domain.trim() || !value.trim()) return;
          onAdd(domain.trim(), value.trim());
          setDomain("");
          setValue("");
        }}
      >
        <input
          type="text"
          value={domain}
          placeholder="metruyencv.com"
          aria-label="Domain"
          onChange={(event) => setDomain(event.target.value)}
        />
        <input
          type="text"
          value={value}
          placeholder="sid=...; remember=..."
          aria-label="Cookie"
          onChange={(event) => setValue(event.target.value)}
        />
        <button type="submit" disabled={busy}>
          Thêm
        </button>
      </form>
    </>
  );
}

function ApiKeyEditor({
  hints,
  onSave,
  busy,
}: {
  hints: Record<string, string | null>;
  onSave: (provider: string, key: string | null) => void;
  busy: boolean;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  return (
    <ul className="source-list">
      {PROVIDERS.map(({ key, label }) => (
        <li key={key}>
          <strong style={{ minWidth: "5.5rem" }}>{label}</strong>
          {hints[key] ? (
            <Badge tone="ok" title="Đã lưu key">
              {hints[key]}
            </Badge>
          ) : (
            <span className="muted small">chưa có</span>
          )}
          <input
            type="password"
            value={drafts[key] ?? ""}
            placeholder="Dán key mới"
            aria-label={`API key ${label}`}
            onChange={(event) => setDrafts({ ...drafts, [key]: event.target.value })}
          />
          <button
            type="button"
            disabled={busy || !(drafts[key] ?? "").trim()}
            onClick={() => {
              onSave(key, drafts[key].trim());
              setDrafts({ ...drafts, [key]: "" });
            }}
          >
            Lưu
          </button>
          {hints[key] && (
            <button type="button" disabled={busy} onClick={() => onSave(key, null)}>
              Xoá
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
